import json

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponseBadRequest, JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from chat import openrouter
from chat.views import _fallback_free_model
from docparse import extract as ex

from . import indexer, search
from .models import RagChat, RagDocument, RagMessage

RAG_ACCEPT = ",".join(e for e in sorted(ex.SUPPORTED_EXT) if e not in ex.IMAGE_EXT)

SYSTEM = """You are "Uncle RAG", an assistant that answers questions using ONLY the provided document excerpts.
Rules:
- Answer in the same language as the user's question (default Thai). Use clear Markdown.
- Base every statement on the excerpts. Cite sources inline with their numbers in square brackets, e.g. [1] or [2][3], right after the fact they support.
- If the excerpts do not contain the answer, say clearly that it was not found in the uploaded documents (you may suggest what to search for). Do not use outside knowledge to fill gaps.
- Quote exact wording for important definitions, numbers, dates and conditions.
- If excerpts conflict, point out the conflict and cite both."""


def _pick_model(user, chat=None):
    if chat and chat.model:
        return chat.model
    m = user.profile.default_model
    if m and (user.can_use_paid_models or openrouter.is_free_model(m)):
        return m
    return "openrouter/auto" if user.can_use_paid_models else _fallback_free_model()


def _default_embed(user):
    return settings.RAG_DEFAULT_EMBED_MODEL if user.can_use_paid_models else settings.RAG_FREE_EMBED_MODEL


def _doc_json(d: RagDocument) -> dict:
    return {"id": d.pk, "name": d.original_name, "size": d.size, "status": d.status, "status_label": d.get_status_display(),
            "progress": d.progress, "error": d.error, "warnings": d.warnings, "pages": d.pages, "chunks": d.n_chunks,
            "chars": d.n_chars, "embed_model": d.embed_model}


@login_required
def index(request, chat_id=None):
    chat = get_object_or_404(RagChat, pk=chat_id, user=request.user) if chat_id else None
    if chat:
        indexer.resume_stuck(chat, request.user.profile.api_key)
    msgs = list(chat.messages.all()) if chat else []
    return render(request, "rag/rag.html", {
        "chat": chat,
        "chats": request.user.rag_chats.all()[:100],
        "docs_json": [_doc_json(d) for d in chat.documents.all()] if chat else [],
        "chat_messages": msgs,
        "sources_json": {str(m.pk): m.sources for m in msgs if m.role == "assistant" and m.sources},
        "current_model": _pick_model(request.user, chat),
        "embed_model": (chat.embed_model if chat else "") or _default_embed(request.user),
        "top_k": chat.top_k if chat else settings.RAG_TOP_K,
        "has_api_key": request.user.profile.has_api_key,
        "accept": RAG_ACCEPT,
        "max_mb": settings.DOC_MAX_UPLOAD_MB,
    })


@login_required
@require_POST
def api_upload(request):
    user = request.user
    files = request.FILES.getlist("files")
    if not files:
        return JsonResponse({"error": "ไม่มีไฟล์"}, status=400)
    cid = request.POST.get("chat_id")
    chat = None
    if cid:
        chat = RagChat.objects.filter(pk=cid, user=user).first()
        if chat is None:
            raise Http404
    errors, created = [], []
    for up in files:
        try:
            ex.check_supported(up.name)
            if ex.ext_of(up.name) in ex.IMAGE_EXT:
                raise ex.UnsupportedFile("RAG รองรับเฉพาะไฟล์เอกสาร (รูปภาพให้ใช้หน้า Data Analyst)")
            if up.size > settings.DOC_MAX_UPLOAD_MB * 1024 * 1024:
                raise ex.UnsupportedFile(f"ใหญ่เกิน {settings.DOC_MAX_UPLOAD_MB} MB")
        except ex.UnsupportedFile as e:
            errors.append(f"{up.name}: {e}")
            continue
        if chat is None:
            chat = RagChat.objects.create(user=user, title=up.name.rsplit(".", 1)[0][:200], model=_pick_model(user),
                                          embed_model=_default_embed(user), top_k=settings.RAG_TOP_K)
        doc = RagDocument(chat=chat, original_name=up.name[:255], size=up.size)
        doc.file.save(up.name, up, save=True)
        indexer.start(doc, user.profile.api_key, chat.embed_model)
        doc.refresh_from_db()
        created.append(_doc_json(doc))
    if chat:
        chat.save()
    return JsonResponse({
        "ok": bool(created), "chat_id": chat.pk if chat else None, "chat_title": chat.title if chat else "",
        "url": reverse("rag:chat", args=[chat.pk]) if chat else None, "docs": created, "errors": errors,
    }, status=200 if created or not errors else 400)


@login_required
@require_GET
def api_docs(request, chat_id):
    chat = get_object_or_404(RagChat, pk=chat_id, user=request.user)
    indexer.resume_stuck(chat, request.user.profile.api_key)
    return JsonResponse({"docs": [_doc_json(d) for d in chat.documents.all()]})


@login_required
@require_POST
def api_delete_doc(request, pk):
    doc = get_object_or_404(RagDocument, pk=pk, chat__user=request.user)
    chat_id = doc.chat_id
    doc.delete()
    search.invalidate(chat_id)
    return JsonResponse({"ok": True})


@login_required
@require_GET
def api_embed_models(request):
    models = indexer.get_embed_models()
    return JsonResponse({"models": models, "can_use_paid": request.user.can_use_paid_models})


@login_required
@require_POST
def api_settings(request, chat_id):
    chat = get_object_or_404(RagChat, pk=chat_id, user=request.user)
    try:
        body = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return HttpResponseBadRequest("invalid json")
    reindexed = 0
    top_k = body.get("top_k")
    if top_k is not None:
        chat.top_k = max(2, min(int(top_k), 15))
    em = (body.get("embed_model") or "").strip()
    if em and em != chat.embed_model:
        info = next((m for m in indexer.get_embed_models() if m["id"] == em), None)
        if info is None:
            return JsonResponse({"error": "ไม่พบโมเดล embedding นี้"}, status=400)
        if not request.user.can_use_paid_models and not info["is_free"]:
            return JsonResponse({"error": "บัญชีของคุณใช้ได้เฉพาะโมเดลฟรี"}, status=403)
        chat.embed_model = em
        for d in chat.documents.exclude(status=RagDocument.Status.ERROR):
            indexer.start(d, request.user.profile.api_key, em, reembed_only=True)
            reindexed += 1
    chat.save()
    search.invalidate(chat.pk)
    return JsonResponse({"ok": True, "embed_model": chat.embed_model, "top_k": chat.top_k, "reindexed": reindexed})


def _sse(ev: dict) -> str:
    return f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"


@login_required
@require_POST
def api_ask(request):
    try:
        body = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return HttpResponseBadRequest("invalid json")
    user = request.user
    chat = get_object_or_404(RagChat, pk=body.get("chat_id"), user=user)
    question = (body.get("message") or "").strip()
    model = (body.get("model") or "").strip()
    if not question:
        return JsonResponse({"error": "กรุณาพิมพ์คำถาม"}, status=400)
    api_key = user.profile.api_key
    if not api_key:
        return JsonResponse({"error": "ยังไม่ได้ตั้งค่า OpenRouter API Key"}, status=400)
    if not user.can_use_paid_models and not openrouter.is_free_model(model):
        return JsonResponse({"error": f"บัญชีประเภท {user.get_role_display()} ใช้ได้เฉพาะโมเดลฟรี"}, status=403)
    if not chat.documents.filter(status=RagDocument.Status.READY).exists():
        msg = "เอกสารยังประมวลผลไม่เสร็จ รอสักครู่" if chat.documents.exists() else "อัปโหลดเอกสารก่อนเริ่มถาม"
        return JsonResponse({"error": msg}, status=400)

    chat.model = model
    chat.save()
    prev = list(chat.messages.order_by("-created_at", "-id")[:6])[::-1]
    history = [{"role": m.role, "content": m.content} for m in prev if m.content]
    last_q = next((m.content for m in reversed(prev) if m.role == "user"), "")
    RagMessage.objects.create(chat=chat, role="user", content=question)

    def stream():
        yield _sse({"type": "status", "text": "กำลังค้นหาในเอกสาร…"})
        # คำถามต่อเนื่องสั้น ๆ (เช่น "แล้วข้อ 2 ล่ะ") → รวมคำถามก่อนหน้าเพื่อค้นหาให้ตรงขึ้น
        query = f"{last_q}\n{question}" if last_q and len(question) < 40 else question
        qvec, note = None, ""
        uses_vec = chat.documents.filter(status="ready", embed_model=chat.embed_model).exclude(embed_model="").exists()
        if uses_vec:
            try:
                qvec = indexer.embed(api_key, chat.embed_model, [query])[0]
            except ValueError as e:
                note = f"(ค้นหาเชิงความหมายไม่สำเร็จ: {e} — ใช้การค้นด้วยคำแทน)"
        hits = search.search(chat.pk, query, chat.top_k, qvec, chat.embed_model)
        sources = [{"n": i + 1, "doc": h["doc"], "doc_id": h["doc_id"], "loc": h["loc"], "text": h["text"][:1500],
                    "score": h["score"], "similarity": h["similarity"]} for i, h in enumerate(hits)]
        yield _sse({"type": "sources", "sources": sources, "mode": "hybrid" if qvec is not None else "keyword", "note": note})
        if sources:
            ctx = "\n\n".join(f"[{s['n']}] (ไฟล์: {s['doc']}{' — ' + s['loc'] if s['loc'] else ''})\n{s['text']}" for s in sources)
        else:
            ctx = "(ไม่พบข้อความที่เกี่ยวข้องในเอกสาร)"
        msgs = [{"role": "system", "content": f"{SYSTEM}\n\nDOCUMENT EXCERPTS:\n{ctx}"}] + history + [{"role": "user", "content": question}]
        yield _sse({"type": "status", "text": "กำลังเขียนคำตอบ…"})
        parts, failed = [], False
        for ev in openrouter.stream_chat(api_key, model, msgs, 0.2):
            if ev["type"] == "delta":
                parts.append(ev["content"])
            elif ev["type"] == "error":
                failed = True
            if ev["type"] in ("delta", "error"):
                yield _sse(ev)
        RagMessage.objects.create(chat=chat, role="assistant", content="".join(parts), sources=sources, model=model)
        yield _sse({"type": "done", "failed": failed})

    resp = StreamingHttpResponse(stream(), content_type="text/event-stream; charset=utf-8")
    resp["Cache-Control"] = "no-cache"
    resp["X-Accel-Buffering"] = "no"
    return resp


@login_required
@require_POST
def api_rename(request, pk):
    c = get_object_or_404(RagChat, pk=pk, user=request.user)
    try:
        title = (json.loads(request.body or b"{}").get("title") or "").strip()
    except json.JSONDecodeError:
        title = ""
    if not title:
        return JsonResponse({"error": "ชื่อว่าง"}, status=400)
    c.title = title[:200]
    c.save(update_fields=["title"])
    return JsonResponse({"ok": True, "title": c.title})


@login_required
@require_POST
def api_delete(request, pk):
    c = get_object_or_404(RagChat, pk=pk, user=request.user)
    for d in c.documents.all():
        d.delete()
    search.invalidate(c.pk)
    c.delete()
    return JsonResponse({"ok": True})
