import json
import os

import requests
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.files.base import ContentFile
from django.http import Http404, HttpResponseBadRequest, JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from chat import openrouter
from chat.views import _fallback_free_model
from docparse import extract as ex
from docparse.tables import infer_types

from . import engine
from .models import AnalysisFile, AnalysisMessage, AnalysisSession

SUGGESTIONS_TABLE = ["สรุปภาพรวมข้อมูลนี้ พร้อมกราฟสำคัญ", "แนวโน้มรายเดือนเป็นอย่างไร", "Top 10 ที่มียอดสูงสุด", "มีความผิดปกติหรือจุดที่น่าสังเกตอะไรบ้าง"]
SUGGESTIONS_DOC = ["สรุปเนื้อหาสำคัญของเอกสาร", "ดึงตัวเลขสำคัญออกมาเป็นตาราง พร้อมกราฟ", "มีประเด็นความเสี่ยงหรือข้อควรระวังอะไรบ้าง", "ทำ Action items จากเอกสารนี้"]


def _pick_model(user, session=None):
    if session and session.model:
        return session.model
    m = user.profile.default_model
    if m and (user.can_use_paid_models or openrouter.is_free_model(m)):
        return m
    return "openrouter/auto" if user.can_use_paid_models else _fallback_free_model()


def _file_json(f: AnalysisFile) -> dict:
    return {"id": f.pk, "name": f.original_name, "kind": f.kind, "kind_label": f.get_kind_display(), "size": f.size, "meta": f.meta}


@login_required
def index(request, session_id=None):
    session = get_object_or_404(AnalysisSession, pk=session_id, user=request.user) if session_id else None
    files = list(session.files.all()) if session else []
    has_table = any(f.kind == "table" for f in files)
    msgs = list(session.messages.all()) if session else []
    results = {str(m.pk): {"charts": m.charts, "metrics": m.metrics, "tables": m.tables} for m in msgs
               if m.role == "assistant" and (m.charts or m.metrics or m.tables)}
    return render(request, "analyst/analyst.html", {
        "session": session,
        "sessions": request.user.analysis_sessions.all()[:100],
        "files": files,
        "files_json": [_file_json(f) for f in files],
        "chat_messages": msgs,
        "results_json": results,
        "current_model": _pick_model(request.user, session),
        "has_api_key": request.user.profile.has_api_key,
        "suggestions": SUGGESTIONS_TABLE if has_table or not files else SUGGESTIONS_DOC,
        "accept": ex.ACCEPT_ATTR,
        "max_mb": settings.DOC_MAX_UPLOAD_MB,
    })


@login_required
@require_POST
def api_upload(request):
    user = request.user
    files = request.FILES.getlist("files")
    if not files:
        return JsonResponse({"error": "ไม่มีไฟล์"}, status=400)
    sid = request.POST.get("session_id")
    session = None
    if sid:
        session = AnalysisSession.objects.filter(pk=sid, user=user).first()
        if session is None:
            raise Http404
    created, errors = [], []
    for up in files:
        try:
            ex.check_supported(up.name)
            if up.size > settings.DOC_MAX_UPLOAD_MB * 1024 * 1024:
                raise ex.UnsupportedFile(f"ใหญ่เกิน {settings.DOC_MAX_UPLOAD_MB} MB")
        except ex.UnsupportedFile as e:
            errors.append(f"{up.name}: {e}")
            continue
        if session is None:
            session = AnalysisSession.objects.create(user=user, title=up.name[:200], model=_pick_model(user))
        af = AnalysisFile(session=session, original_name=up.name[:255], size=up.size, kind="text")
        af.file.save(up.name, up, save=False)
        try:
            doc = ex.extract(af.file.path, up.name)
        except Exception as e:  # noqa: BLE001 — ไฟล์เสีย/รูปแบบแปลก
            af.file.delete(save=False)
            errors.append(f"{up.name}: อ่านไฟล์ไม่สำเร็จ ({e})")
            continue
        af.kind = doc.kind
        meta = {"warnings": doc.warnings}
        if doc.kind == "table":
            meta["sheets"] = [{"name": t.name, "rows": len(t.rows), "columns": t.columns[:60], "types": infer_types(t)[:60]}
                              for t in doc.tables]
            path = af.file.path + ".tables.json"
            ex.save_tables(doc.tables, path)
            with open(path, "rb") as fh:
                af.cache.save(f"{up.name}.tables.json", ContentFile(fh.read()), save=False)
            os.unlink(path)
        elif doc.kind == "text":
            text = doc.text
            meta.update(chars=len(text), pages=doc.pages)
            af.cache.save(f"{up.name}.txt", ContentFile(text.encode("utf-8")), save=False)
        else:
            af.media_type = doc.media_type
        af.meta = meta
        af.save()
        created.append(_file_json(af))
    if session:
        session.save()  # bump updated_at
    return JsonResponse({
        "ok": bool(created), "session_id": session.pk if session else None, "session_title": session.title if session else "",
        "url": reverse("analyst:session", args=[session.pk]) if session else None,
        "files": created, "errors": errors,
    }, status=200 if created or not errors else 400)


@login_required
@require_POST
def api_delete_file(request, pk):
    f = get_object_or_404(AnalysisFile, pk=pk, session__user=request.user)
    f.delete()
    return JsonResponse({"ok": True})


def _sse(ev: dict) -> str:
    return f"data: {json.dumps(ev, ensure_ascii=False, default=str)}\n\n"


@login_required
@require_POST
def api_ask(request):
    try:
        body = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return HttpResponseBadRequest("invalid json")
    user = request.user
    question = (body.get("message") or "").strip()
    model = (body.get("model") or "").strip()
    session = get_object_or_404(AnalysisSession, pk=body.get("session_id"), user=user)
    if not question:
        return JsonResponse({"error": "กรุณาพิมพ์คำถาม"}, status=400)
    api_key = user.profile.api_key
    if not api_key:
        return JsonResponse({"error": "ยังไม่ได้ตั้งค่า OpenRouter API Key"}, status=400)
    if not user.can_use_paid_models and not openrouter.is_free_model(model):
        return JsonResponse({"error": f"บัญชีประเภท {user.get_role_display()} ใช้ได้เฉพาะโมเดลฟรี"}, status=403)
    if not session.files.exists():
        return JsonResponse({"error": "อัปโหลดไฟล์ก่อนเริ่มวิเคราะห์"}, status=400)

    session.model = model
    session.save()
    prev = list(session.messages.order_by("-created_at", "-id")[:8])[::-1]
    history = [{"role": m.role, "content": m.content or "(แสดงกราฟ)"} for m in prev if m.content or m.charts]
    history_q = [m.content for m in prev if m.role == "user"]
    AnalysisMessage.objects.create(session=session, role="user", content=question)

    info = openrouter.find_model(model) or {}
    use_images = "image" in (info.get("input_modalities") or [])

    def stream():
        b = engine.load_bundle(session)
        res = None
        if b.has_tables:
            yield _sse({"type": "status", "text": "กำลังวางแผนการวิเคราะห์…"})
            try:
                spec = engine.plan(api_key, model, b, question, history_q)
            except (ValueError, requests.RequestException) as e:
                spec = {}
                yield _sse({"type": "status", "text": f"AI วางแผนไม่สำเร็จ ({e}) — ใช้การสรุปอัตโนมัติแทน"})
            if not any(spec.get(k) for k in ("metrics", "charts", "tables")) and not history_q:
                spec = engine.tb.auto_overview(b.tables, b.types)
            yield _sse({"type": "status", "text": "กำลังคำนวณจากข้อมูลทั้งหมด…"})
            res = engine.execute(b, spec)
            yield _sse({"type": "results", "metrics": res["metrics"], "charts": res["charts"], "tables": res["tables"]})
        yield _sse({"type": "status", "text": "กำลังเขียนสรุป…"})
        msgs = engine.build_answer_messages(b, res, question, history, use_images)
        parts, failed = [], False
        for ev in openrouter.stream_chat(api_key, model, msgs, 0.3):
            if ev["type"] == "delta":
                parts.append(ev["content"])
            elif ev["type"] == "error":
                failed = True
            if ev["type"] in ("delta", "error"):
                yield _sse(ev)
        AnalysisMessage.objects.create(
            session=session, role="assistant", content="".join(parts), model=model,
            charts=res["charts"] if res else [], metrics=res["metrics"] if res else [], tables=res["tables"] if res else [],
        )
        yield _sse({"type": "done", "failed": failed})

    resp = StreamingHttpResponse(stream(), content_type="text/event-stream; charset=utf-8")
    resp["Cache-Control"] = "no-cache"
    resp["X-Accel-Buffering"] = "no"
    return resp


@login_required
@require_POST
def api_rename(request, pk):
    s = get_object_or_404(AnalysisSession, pk=pk, user=request.user)
    try:
        title = (json.loads(request.body or b"{}").get("title") or "").strip()
    except json.JSONDecodeError:
        title = ""
    if not title:
        return JsonResponse({"error": "ชื่อว่าง"}, status=400)
    s.title = title[:200]
    s.save(update_fields=["title"])
    return JsonResponse({"ok": True, "title": s.title})


@login_required
@require_POST
def api_delete(request, pk):
    s = get_object_or_404(AnalysisSession, pk=pk, user=request.user)
    for f in s.files.all():
        f.delete()
    s.delete()
    return JsonResponse({"ok": True})
