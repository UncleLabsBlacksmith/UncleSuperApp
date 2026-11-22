"""Hybrid retrieval: BM25 (รองรับภาษาไทยด้วย character bigram) + vector similarity → รวมด้วย Reciprocal Rank Fusion"""
import math
import re
from array import array
from collections import Counter

import threading

from django.db.models import Count, Max

from .models import RagChunk, RagDocument

_INDEX: dict[int, tuple] = {}  # chat_id -> (version, index) — เก็บใน memory ของ process (เร็วกว่า cache ที่ต้อง pickle)
_LOCK = threading.Lock()

_tok_re = re.compile(r"[a-z0-9]+|[฀-๿]+")
STOP = {"the", "a", "an", "of", "and", "or", "to", "in", "is", "are", "for", "on", "with", "what", "how", "ที่", "และ", "ของ"}


def tokenize(text: str) -> list[str]:
    toks = []
    for m in _tok_re.findall(text.lower()):
        if "฀" <= m[0] <= "๿":  # ภาษาไทยไม่มีช่องว่างระหว่างคำ → ใช้ bigram ของตัวอักษร
            if len(m) == 1:
                continue
            toks.extend(m[i:i + 2] for i in range(len(m) - 1))
        elif len(m) > 1 and m not in STOP:
            toks.append(m)
    return toks


def _build(chat_id: int):
    rows = list(RagChunk.objects.filter(chat_id=chat_id, document__status="ready")
                .values_list("id", "text", "loc", "document_id", "document__original_name", "document__embed_model", "embedding"))
    tfs, df, lens = [], Counter(), []
    for r in rows:
        tf = Counter(tokenize(r[1]))
        tfs.append(tf)
        df.update(tf.keys())
        lens.append(sum(tf.values()))
    vecs = [array("f", bytes(r[6])) if r[6] else None for r in rows]
    return {
        "meta": [{"id": r[0], "text": r[1], "loc": r[2], "doc_id": r[3], "doc": r[4], "embed_model": r[5]} for r in rows],
        "tfs": tfs, "df": df, "avgdl": (sum(lens) / len(lens)) if lens else 1, "lens": lens, "vecs": vecs,
    }


def _version(chat_id: int):
    agg = RagChunk.objects.filter(chat_id=chat_id, document__status="ready").aggregate(n=Count("id"), m=Max("id"))
    docs = tuple(RagDocument.objects.filter(chat_id=chat_id, status="ready").values_list("id", "embed_model"))
    return (agg["n"], agg["m"], docs)


def get_index(chat_id: int):
    ver = _version(chat_id)
    with _LOCK:
        hit = _INDEX.get(chat_id)
        if hit and hit[0] == ver:
            return hit[1]
    idx = _build(chat_id)
    with _LOCK:
        _INDEX[chat_id] = (ver, idx)
        if len(_INDEX) > 20:  # จำกัดหน่วยความจำ
            _INDEX.pop(next(iter(_INDEX)))
    return idx


def invalidate(chat_id: int):
    with _LOCK:
        _INDEX.pop(chat_id, None)


def bm25(idx, query: str, k1=1.4, b=0.75) -> list[tuple[int, float]]:
    q = Counter(tokenize(query))
    if not q or not idx["meta"]:
        return []
    N = len(idx["meta"])
    scores = []
    for i, tf in enumerate(idx["tfs"]):
        s = 0.0
        dl = idx["lens"][i] or 1
        for term in q:
            f = tf.get(term)
            if not f:
                continue
            n = idx["df"][term]
            idf = math.log(1 + (N - n + 0.5) / (n + 0.5))
            s += idf * f * (k1 + 1) / (f + k1 * (1 - b + b * dl / idx["avgdl"]))
        if s > 0:
            scores.append((i, s))
    scores.sort(key=lambda x: -x[1])
    return scores


def vector(idx, qvec: array, model: str) -> list[tuple[int, float]]:
    out = []
    for i, v in enumerate(idx["vecs"]):
        if v is None or idx["meta"][i]["embed_model"] != model or len(v) != len(qvec):
            continue
        out.append((i, sum(a * b for a, b in zip(v, qvec))))
    out.sort(key=lambda x: -x[1])
    return out


def search(chat_id: int, query: str, top_k: int, qvec: array | None = None, model: str = "") -> list[dict]:
    idx = get_index(chat_id)
    lex = bm25(idx, query)[:60]
    vec = vector(idx, qvec, model)[:60] if qvec is not None else []
    fused = {}
    for rank, (i, _) in enumerate(lex):
        fused[i] = fused.get(i, 0) + 1 / (60 + rank)
    for rank, (i, _) in enumerate(vec):
        fused[i] = fused.get(i, 0) + 1.2 / (60 + rank)  # ให้น้ำหนัก semantic มากกว่าเล็กน้อย
    vec_score = dict(vec)
    best = sorted(fused, key=lambda i: -fused[i])[:top_k]
    out = []
    for i in best:
        m = idx["meta"][i]
        out.append({**m, "score": round(fused[i] * 100, 2), "similarity": round(vec_score[i], 3) if i in vec_score else None})
    return out
