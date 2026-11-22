import base64
import json
import time

import requests
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.files.base import ContentFile
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.template.loader import render_to_string
from django.views.decorators.http import require_GET, require_POST

from . import client
from .models import EXT_BY_MEDIA_TYPE, GeneratedImage, Generation, ImageSession, ReferenceImage


def _sniff_image(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _data_url(data: bytes, media_type: str) -> str:
    return f"data:{media_type};base64,{base64.b64encode(data).decode()}"


def _can_use(user, model: dict) -> bool:
    return user.can_use_paid_models or model.get("is_free")


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------
@login_required
def index(request, session_id=None):
    session = None
    if session_id is not None:
        session = get_object_or_404(ImageSession, pk=session_id, user=request.user)
    generations = (
        session.generations.order_by("-created_at", "-id").prefetch_related("images", "references") if session else []
    )
    prefill_ref = None
    ref_id = request.GET.get("ref")
    if ref_id and ref_id.isdigit():
        prefill_ref = GeneratedImage.objects.filter(pk=ref_id, generation__session__user=request.user).first()
    return render(
        request,
        "imagegen/generate.html",
        {
            "session": session,
            "sessions": request.user.image_sessions.all()[:100],
            "generations": generations,
            "has_api_key": request.user.profile.has_api_key,
            "current_model": request.GET.get("model") or (session.model if session else ""),
            "prefill_prompt": request.GET.get("prompt", ""),
            "prefill_ref": prefill_ref,
        },
    )


@login_required
def gallery(request):
    qs = GeneratedImage.objects.filter(generation__session__user=request.user).select_related(
        "generation", "generation__session"
    )
    q = request.GET.get("q", "").strip()
    model = request.GET.get("model", "").strip()
    if q:
        qs = qs.filter(generation__prompt__icontains=q)
    if model:
        qs = qs.filter(generation__model=model)
    models = (
        GeneratedImage.objects.filter(generation__session__user=request.user)
        .values("generation__model")
        .annotate(n=Count("id"))
        .order_by("-n")
    )
    page = Paginator(qs, 48).get_page(request.GET.get("page"))
    return render(
        request,
        "imagegen/gallery.html",
        {"page": page, "q": q, "model": model, "models": models, "total": qs.count()},
    )


@login_required
@require_GET
def file_view(request, kind, pk):
    Model = {"out": GeneratedImage, "ref": ReferenceImage}.get(kind)
    if Model is None:
        raise Http404
    obj = get_object_or_404(Model, pk=pk, generation__session__user=request.user)
    try:
        fh = obj.file.open("rb")
    except FileNotFoundError:
        raise Http404
    as_download = request.GET.get("download") == "1"
    ext = EXT_BY_MEDIA_TYPE.get(obj.media_type, "png")
    resp = FileResponse(fh, content_type=obj.media_type, as_attachment=as_download,
                        filename=f"uncle-{kind}-{obj.pk}.{ext}")
    resp["Content-Security-Policy"] = "default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'; sandbox"
    resp["Cache-Control"] = "private, max-age=86400"
    return resp


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
@login_required
@require_GET
def api_models(request):
    try:
        models = client.get_image_models(force=request.GET.get("refresh") == "1")
    except requests.RequestException as e:
        return JsonResponse({"error": f"โหลดรายชื่อโมเดลไม่ได้: {e}"}, status=502)
    return JsonResponse(
        {"models": models, "can_use_paid": request.user.can_use_paid_models, "role": request.user.get_role_display()}
    )


@login_required
@require_POST
def api_generate(request):
    user = request.user
    profile = user.profile
    prompt = (request.POST.get("prompt") or "").strip()
    model_id = (request.POST.get("model") or "").strip()
    session_id = request.POST.get("session_id") or None

    if not prompt:
        return JsonResponse({"error": "กรุณาพิมพ์ prompt"}, status=400)
    api_key = profile.api_key
    if not api_key:
        return JsonResponse({"error": "ยังไม่ได้ตั้งค่า OpenRouter API Key — ไปที่หน้า ตั้งค่า"}, status=400)
    model = client.find_image_model(model_id)
    if model is None:
        return JsonResponse({"error": "ไม่พบโมเดลสร้างภาพนี้"}, status=400)
    if not _can_use(user, model):
        return JsonResponse(
            {"error": f"บัญชีประเภท {user.get_role_display()} ใช้ได้เฉพาะโมเดลฟรี — ติดต่อผู้ดูแลเพื่ออัปเกรดเป็น Pro"},
            status=403,
        )

    try:
        raw_params = json.loads(request.POST.get("params") or "{}")
    except json.JSONDecodeError:
        raw_params = {}
    params = client.clean_params(model, raw_params)

    # ---- ภาพอ้างอิง: ไฟล์ที่อัปโหลด + ภาพเดิมจากแกลเลอรี ----
    refs: list[tuple[bytes, str, str]] = []  # (data, media_type, name)
    for f in request.FILES.getlist("references"):
        if f.size > settings.IMAGE_REF_MAX_BYTES:
            return JsonResponse({"error": f"ไฟล์ {f.name} ใหญ่เกิน {settings.IMAGE_REF_MAX_BYTES // 1024 // 1024} MB"}, status=400)
        data = f.read()
        mt = _sniff_image(data)
        if not mt:
            return JsonResponse({"error": f"ไฟล์ {f.name} ไม่ใช่ภาพที่รองรับ (PNG, JPG, WEBP, GIF)"}, status=400)
        refs.append((data, mt, f.name[:255]))
    ids = [i for i in (request.POST.get("ref_image_ids") or "").split(",") if i.strip().isdigit()]
    for img in GeneratedImage.objects.filter(pk__in=ids, generation__session__user=user):
        if img.media_type == "image/svg+xml":
            continue
        with img.file.open("rb") as fh:
            refs.append((fh.read(), img.media_type, f"gallery-{img.pk}"))

    if len(refs) > model["refs_max"]:
        msg = "โมเดลนี้ไม่รองรับภาพอ้างอิง" if model["refs_max"] == 0 else f"โมเดลนี้รับภาพอ้างอิงได้สูงสุด {model['refs_max']} ภาพ"
        return JsonResponse({"error": msg}, status=400)
    if len(refs) < model["refs_min"]:
        return JsonResponse({"error": f"โมเดลนี้ต้องมีภาพอ้างอิงอย่างน้อย {model['refs_min']} ภาพ"}, status=400)

    # ---- บันทึก session / generation ----
    if session_id:
        session = ImageSession.objects.filter(pk=session_id, user=user).first()
        if session is None:
            raise Http404
        is_new = False
    else:
        session = ImageSession.objects.create(user=user, title=prompt[:60], model=model_id)
        is_new = True
    session.model = model_id
    session.save()

    gen = Generation.objects.create(session=session, prompt=prompt, model=model_id, params=params)
    for data, mt, name in refs:
        ext = EXT_BY_MEDIA_TYPE.get(mt, "png")
        ref = ReferenceImage(generation=gen, media_type=mt, original_name=name)
        ref.file.save(f"ref.{ext}", ContentFile(data), save=True)

    t0 = time.monotonic()
    ok, result = client.generate(api_key, model_id, prompt, params, [_data_url(d, mt) for d, mt, _ in refs])
    gen.duration_ms = int((time.monotonic() - t0) * 1000)

    if ok:
        for item in result["images"]:
            try:
                data = base64.b64decode(item["b64"])
            except (ValueError, TypeError):
                continue
            mt = item["media_type"]
            img = GeneratedImage(generation=gen, media_type=mt)
            img.file.save(f"out.{EXT_BY_MEDIA_TYPE.get(mt, 'png')}", ContentFile(data), save=True)
        gen.cost = result.get("cost")
        gen.status = Generation.Status.SUCCESS if gen.images.exists() else Generation.Status.ERROR
        if gen.status == Generation.Status.ERROR:
            gen.error = "ถอดรหัสภาพไม่สำเร็จ"
    else:
        gen.status = Generation.Status.ERROR
        gen.error = result["message"]
    gen.save()

    html = render_to_string("imagegen/_generation.html", {"g": gen}, request=request)
    return JsonResponse(
        {
            "ok": gen.status == Generation.Status.SUCCESS,
            "error": gen.error or None,
            "session_id": session.pk,
            "session_title": session.title,
            "is_new": is_new,
            "html": html,
        }
    )


@login_required
@require_POST
def api_delete_image(request, pk):
    img = get_object_or_404(GeneratedImage, pk=pk, generation__session__user=request.user)
    img.delete()
    return JsonResponse({"ok": True})


@login_required
@require_POST
def api_delete_session(request, pk):
    session = get_object_or_404(ImageSession, pk=pk, user=request.user)
    # ลบไฟล์ด้วย (post_delete signal ทำงานต่อ object เมื่อ cascade)
    session.delete()
    return JsonResponse({"ok": True})


@login_required
@require_POST
def api_rename_session(request, pk):
    session = get_object_or_404(ImageSession, pk=pk, user=request.user)
    try:
        title = (json.loads(request.body or b"{}").get("title") or "").strip()
    except json.JSONDecodeError:
        title = ""
    if not title:
        return JsonResponse({"error": "ชื่อว่าง"}, status=400)
    session.title = title[:200]
    session.save(update_fields=["title"])
    return JsonResponse({"ok": True, "title": session.title})
