"""แยกข้อความ → แบ่ง chunk → สร้าง embedding (ทำงานเบื้องหลังใน thread)"""
import logging
import math
import re
import threading
import time
from array import array

import requests
from django.conf import settings
from django.core.cache import cache
from django.db import close_old_connections
from django.utils import timezone

from chat.openrouter import _error_message, _headers
from docparse import extract as ex

from . import search
from .models import RagChunk, RagDocument

log = logging.getLogger(__name__)
_active: set[int] = set()
_active_lock = threading.Lock()
EMBED_MODELS_CACHE_KEY = "openrouter:embed-models:v1"


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------
def _split_long(text: str, size: int) -> list[str]:
    out = []
    while len(text) > size:
        cut = max(text.rfind("\n", 0, size), text.rfind(". ", 0, size), text.rfind(" ", 0, size))
        if cut < size * 0.5:
            cut = size
        out.append(text[:cut].strip())
        text = text[cut:]
    if text.strip():
        out.append(text.strip())
    return out


def chunk_segments(segments, size=None, overlap=None) -> list[tuple[str, str]]:
    size = size or settings.RAG_CHUNK_CHARS
    overlap = overlap if overlap is not None else settings.RAG_CHUNK_OVERLAP
    chunks = []
    for seg in segments:
        paras = [p.strip() for p in re.split(r"\n\s*\n", seg.text) if p.strip()]
        pieces = []
        for p in paras:
            pieces.extend(_split_long(p, size) if len(p) > size else [p])
        buf = ""
        for p in pieces:
            if buf and len(buf) + len(p) + 2 > size:
                chunks.append((buf, seg.loc))
                tail = buf[-overlap:] if overlap else ""
                buf = (tail + "\n" if tail else "") + p
            else:
                buf = f"{buf}\n\n{p}" if buf else p
        if buf.strip():
            chunks.append((buf, seg.loc))
    return chunks


# ---------------------------------------------------------------------------
# Embeddings
# ---------------------------------------------------------------------------
def get_embed_models() -> list[dict]:
    cached = cache.get(EMBED_MODELS_CACHE_KEY)
    if cached is not None:
        return cached
    try:
        r = requests.get(f"{settings.OPENROUTER_BASE_URL}/embeddings/models", headers=_headers(), timeout=20)
        r.raise_for_status()
        data = r.json().get("data", [])
    except (requests.RequestException, ValueError):
        return []
    out = []
    for m in data:
        mod = (m.get("architecture") or {}).get("input_modalities") or ["text"]
        if "text" not in mod:
            continue
        price = m.get("pricing") or {}
        try:
            p = float(price.get("prompt") or 0) * 1_000_000
        except ValueError:
            p = 0
        out.append({"id": m["id"], "name": m.get("name") or m["id"], "price": round(p, 4), "is_free": p == 0,
                    "context": m.get("context_length") or 0})
    out.sort(key=lambda m: (not m["is_free"], m["price"]))
    cache.set(EMBED_MODELS_CACHE_KEY, out, settings.OPENROUTER_MODELS_CACHE_SECONDS)
    return out


def _normalize(vec) -> array:
    n = math.sqrt(sum(x * x for x in vec)) or 1.0
    return array("f", (x / n for x in vec))


def embed(api_key: str, model: str, texts: list[str]) -> list[array]:
    out = []
    for i in range(0, len(texts), 32):
        batch = [t[:8000] for t in texts[i:i + 32]]
        for attempt in range(4):
            try:
                r = requests.post(f"{settings.OPENROUTER_BASE_URL}/embeddings", headers=_headers(api_key),
                                  json={"model": model, "input": batch}, timeout=(15, 120))
            except requests.RequestException as e:
                if attempt == 3:
                    raise ValueError(f"เชื่อมต่อ OpenRouter ไม่ได้: {e}")
                time.sleep(2 * (attempt + 1))
                continue
            if r.status_code == 429 or r.status_code >= 500:
                if attempt == 3:
                    raise ValueError(_error_message(r))
                time.sleep(3 * (attempt + 1))
                continue
            if r.status_code != 200:
                raise ValueError(_error_message(r))
            data = sorted(r.json().get("data") or [], key=lambda d: d.get("index", 0))
            if len(data) != len(batch):
                raise ValueError("จำนวน embedding ที่ได้ไม่ตรงกับจำนวนข้อความ")
            out.extend(_normalize(d["embedding"]) for d in data)
            break
    return out


# ---------------------------------------------------------------------------
# Background indexing
# ---------------------------------------------------------------------------
def _run(doc_id: int, api_key: str, embed_model: str, reembed_only: bool):
    close_old_connections()
    try:
        doc = RagDocument.objects.get(pk=doc_id)
        if not reembed_only:
            parsed = ex.extract(doc.file.path, doc.original_name)
            if parsed.kind == "image":
                raise ValueError("RAG ยังไม่รองรับรูปภาพ — ใช้หน้า Data Analyst เพื่อวิเคราะห์รูปภาพ")
            pieces = chunk_segments(parsed.segments)
            if not pieces:
                raise ValueError("ไม่พบข้อความในไฟล์นี้" + (f" — {parsed.warnings[0]}" if parsed.warnings else ""))
            RagChunk.objects.filter(document=doc).delete()
            RagChunk.objects.bulk_create([RagChunk(document=doc, chat_id=doc.chat_id, idx=i, text=t, loc=loc[:120])
                                          for i, (t, loc) in enumerate(pieces)], batch_size=500)
            doc.pages, doc.n_chunks = parsed.pages, len(pieces)
            doc.n_chars = sum(len(t) for t, _ in pieces)
            doc.warnings = parsed.warnings
            doc.progress = 30
            doc.save()
        chunks = list(RagChunk.objects.filter(document=doc).only("id", "text"))
        doc.embed_model = ""
        if embed_model and api_key:
            try:
                total = len(chunks)
                for start in range(0, total, 64):
                    part = chunks[start:start + 64]
                    vecs = embed(api_key, embed_model, [c.text for c in part])
                    for c, v in zip(part, vecs):
                        c.embedding = v.tobytes()
                    RagChunk.objects.bulk_update(part, ["embedding"])
                    RagDocument.objects.filter(pk=doc.pk).update(progress=30 + int(70 * min(total, start + 64) / total))
                doc.embed_model = embed_model
            except ValueError as e:
                RagChunk.objects.filter(document=doc).update(embedding=None)
                doc.warnings = list(doc.warnings or []) + [f"สร้าง embedding ไม่สำเร็จ ({e}) — ใช้การค้นหาด้วยคำแทน"]
        doc.status, doc.progress, doc.error = RagDocument.Status.READY, 100, ""
        doc.save()
    except Exception as e:  # noqa: BLE001
        log.exception("index failed")
        RagDocument.objects.filter(pk=doc_id).update(status=RagDocument.Status.ERROR, error=str(e)[:1000])
    finally:
        with _active_lock:
            _active.discard(doc_id)
        chat_id = RagDocument.objects.filter(pk=doc_id).values_list("chat_id", flat=True).first()
        if chat_id:
            search.invalidate(chat_id)
        close_old_connections()


def start(doc: RagDocument, api_key: str, embed_model: str, reembed_only=False):
    with _active_lock:
        if doc.pk in _active:
            return
        _active.add(doc.pk)
    RagDocument.objects.filter(pk=doc.pk).update(status=RagDocument.Status.PROCESSING, progress=30 if reembed_only else 5,
                                                 error="")
    threading.Thread(target=_run, args=(doc.pk, api_key, embed_model, reembed_only), daemon=True,
                     name=f"rag-index-{doc.pk}").start()


def resume_stuck(chat, api_key: str):
    """เอกสารที่ค้างสถานะ processing (เช่น ปิด server กลางคัน) → เริ่มใหม่"""
    for doc in chat.documents.filter(status=RagDocument.Status.PROCESSING):
        with _active_lock:
            running = doc.pk in _active
        if not running and (timezone.now() - doc.created_at).total_seconds() > 20:
            start(doc, api_key, chat.embed_model)
