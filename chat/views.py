import json

import requests
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponseBadRequest, JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from . import openrouter
from .models import Conversation, Message

FALLBACK_MODEL = "openrouter/auto"


def _fallback_free_model() -> str:
    """เลือกโมเดลฟรีที่ context ยาวที่สุดจากรายการปัจจุบันของ OpenRouter"""
    try:
        free = [m for m in openrouter.get_models() if m["is_free"]]
    except requests.RequestException:
        free = []
    if not free:
        return "openrouter/free"
    return max(free, key=lambda m: m["context_length"] or 0)["id"]


def _pick_model(user, conversation=None) -> str:
    if conversation and conversation.model:
        return conversation.model
    default = user.profile.default_model
    if default and (user.can_use_paid_models or openrouter.is_free_model(default)):
        return default
    return FALLBACK_MODEL if user.can_use_paid_models else _fallback_free_model()


@login_required
def index(request, conv_id=None):
    conversation = None
    if conv_id is not None:
        conversation = get_object_or_404(Conversation, pk=conv_id, user=request.user)
    conversations = request.user.conversations.all()[:100]
    msgs = conversation.messages.exclude(role=Message.Role.SYSTEM) if conversation else []
    limit = request.user.daily_message_limit
    return render(
        request,
        "chat/chat.html",
        {
            "conversation": conversation,
            "conversations": conversations,
            "chat_messages": msgs,
            "current_model": _pick_model(request.user, conversation),
            "has_api_key": request.user.profile.has_api_key,
            "daily_limit": limit,
            "used_today": request.user.messages_sent_today() if limit else None,
        },
    )


@login_required
@require_GET
def api_models(request):
    try:
        models = openrouter.get_models(force=request.GET.get("refresh") == "1")
    except requests.RequestException as e:
        return JsonResponse({"error": f"โหลดรายชื่อโมเดลไม่ได้: {e}"}, status=502)
    return JsonResponse(
        {
            "models": models,
            "can_use_paid": request.user.can_use_paid_models,
            "role": request.user.get_role_display(),
        }
    )


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


@login_required
@require_POST
def api_send(request):
    try:
        body = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return HttpResponseBadRequest("invalid json")

    text = (body.get("message") or "").strip()
    model = (body.get("model") or "").strip()
    conv_id = body.get("conversation_id")
    user = request.user
    profile = user.profile

    if not text:
        return JsonResponse({"error": "กรุณาพิมพ์ข้อความ"}, status=400)
    if not model:
        return JsonResponse({"error": "กรุณาเลือกโมเดล"}, status=400)
    api_key = profile.api_key
    if not api_key:
        return JsonResponse({"error": "ยังไม่ได้ตั้งค่า OpenRouter API Key — ไปที่หน้า ตั้งค่า"}, status=400)
    if not user.can_use_paid_models and not openrouter.is_free_model(model):
        return JsonResponse(
            {"error": f"บัญชีประเภท {user.get_role_display()} ใช้ได้เฉพาะโมเดลฟรี — ติดต่อผู้ดูแลเพื่ออัปเกรดเป็น Pro"},
            status=403,
        )
    limit = user.daily_message_limit
    if limit is not None and user.messages_sent_today() >= limit:
        return JsonResponse({"error": f"ครบโควตา {limit} ข้อความต่อวันแล้ว"}, status=429)

    if conv_id:
        conversation = Conversation.objects.filter(pk=conv_id, user=user).first()
        if conversation is None:
            raise Http404
        is_new = False
    else:
        conversation = Conversation.objects.create(user=user, title=text[:60] or "แชทใหม่", model=model)
        is_new = True

    if conversation.model != model:
        conversation.model = model
    conversation.save()  # อัปเดต updated_at ให้ขึ้นบนสุด

    Message.objects.create(conversation=conversation, role=Message.Role.USER, content=text, model=model)

    # สร้างบริบท: system prompt + ข้อความล่าสุด
    history = list(
        conversation.messages.exclude(role=Message.Role.SYSTEM).order_by("-created_at", "-id")[
            : settings.CHAT_HISTORY_LIMIT
        ]
    )[::-1]
    payload = []
    if profile.system_prompt.strip():
        payload.append({"role": "system", "content": profile.system_prompt.strip()})
    payload += [{"role": m.role, "content": m.content} for m in history]

    def event_stream():
        yield _sse({"type": "meta", "conversation_id": conversation.pk, "title": conversation.title, "is_new": is_new})
        parts, usage, failed = [], {}, False
        try:
            for ev in openrouter.stream_chat(api_key, model, payload, profile.temperature):
                if ev["type"] == "delta":
                    parts.append(ev["content"])
                elif ev["type"] == "usage":
                    usage = ev
                elif ev["type"] == "error":
                    failed = True
                yield _sse(ev)
        finally:
            content = "".join(parts)
            msg = None
            if content:
                msg = Message.objects.create(
                    conversation=conversation,
                    role=Message.Role.ASSISTANT,
                    content=content,
                    model=model,
                    prompt_tokens=usage.get("prompt_tokens"),
                    completion_tokens=usage.get("completion_tokens"),
                )
        yield _sse({"type": "done", "message_id": msg.pk if msg else None, "failed": failed})

    resp = StreamingHttpResponse(event_stream(), content_type="text/event-stream; charset=utf-8")
    resp["Cache-Control"] = "no-cache"
    resp["X-Accel-Buffering"] = "no"
    return resp


@login_required
@require_POST
def api_rename(request, conv_id):
    conversation = get_object_or_404(Conversation, pk=conv_id, user=request.user)
    try:
        title = (json.loads(request.body or b"{}").get("title") or "").strip()
    except json.JSONDecodeError:
        title = ""
    if not title:
        return JsonResponse({"error": "ชื่อว่าง"}, status=400)
    conversation.title = title[:200]
    conversation.save(update_fields=["title"])
    return JsonResponse({"ok": True, "title": conversation.title})


@login_required
@require_POST
def api_delete(request, conv_id):
    conversation = get_object_or_404(Conversation, pk=conv_id, user=request.user)
    conversation.delete()
    return JsonResponse({"ok": True})


@login_required
@require_POST
def api_set_default_model(request):
    try:
        model = (json.loads(request.body or b"{}").get("model") or "").strip()
    except json.JSONDecodeError:
        model = ""
    if not model:
        return JsonResponse({"error": "ไม่มีโมเดล"}, status=400)
    if not request.user.can_use_paid_models and not openrouter.is_free_model(model):
        return JsonResponse({"error": "บัญชีของคุณใช้ได้เฉพาะโมเดลฟรี"}, status=403)
    profile = request.user.profile
    profile.default_model = model
    profile.save(update_fields=["default_model", "updated_at"])
    return JsonResponse({"ok": True})


