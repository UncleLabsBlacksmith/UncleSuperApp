import json
import logging
import os
import re
import tempfile
import zipfile

import requests
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.files.base import ContentFile
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from . import client
from .models import Scene, SceneVersion, VideoProject
from .worker import compose_prompt

logger = logging.getLogger(__name__)

IMAGE_MAGIC = {b"\x89PNG": "png", b"\xff\xd8\xff": "jpg", b"RIFF": "webp"}


def _helper_model(user) -> str:
    return user.profile.default_model or "openrouter/auto"


def _sidebar(user):
    return user.video_projects.only("id", "title", "status", "mode", "seen")[:80]


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------
@login_required
def index(request):
    prefill = None
    src = request.GET.get("from")
    if src and src.isdigit():
        p = VideoProject.objects.filter(pk=src, user=request.user).first()
        if p:
            prefill = {
                "mode": p.mode, "title": p.title, "idea": p.idea, "model": p.model, "config": p.config,
                "style_guide": p.style_guide, "music_prompt": p.music_prompt,
                "scenes": [{"prompt": s.prompt, "narration": s.narration} for s in p.scenes.all()],
            }
    return render(request, "videogen/create.html", {
        "projects": _sidebar(request.user),
        "has_api_key": request.user.profile.has_api_key,
        "helper_model": _helper_model(request.user),
        "prefill": prefill,
        "max_scenes": settings.VIDEO_MAX_SCENES,
    })


@login_required
def project_detail(request, pk):
    project = get_object_or_404(VideoProject, pk=pk, user=request.user)
    if not project.is_active and not project.seen:
        project.seen = True
        project.save(update_fields=["seen"])
    return render(request, "videogen/project.html", {
        "project": project,
        "scenes": project.scenes.prefetch_related("versions"),
        "projects": _sidebar(request.user),
        "voice": (project.config or {}).get("audio_mode") == "voice",
        "ar_css": ((project.config or {}).get("aspect_ratio") or "16:9").replace(":", " / "),
        "captions": _captions(project.config or {}),
    })


def _slug(title: str) -> str:
    s = re.sub(r'[\\/:*?"<>|\s]+', "-", (title or "video").strip())[:60].strip("-")
    return s or "video"


# ---------------------------------------------------------------------------
# Files (รองรับ HTTP Range เพื่อให้เลื่อนดูวิดีโอได้)
# ---------------------------------------------------------------------------
def _ranged_response(request, path: str, content_type: str, download_name: str | None):
    size = os.path.getsize(path)
    rng = request.headers.get("Range", "")
    m = re.match(r"bytes=(\d*)-(\d*)", rng)
    if m and (m.group(1) or m.group(2)):
        start = int(m.group(1)) if m.group(1) else max(0, size - int(m.group(2)))
        end = int(m.group(2)) if m.group(1) and m.group(2) else size - 1
        end = min(end, size - 1)
        if start > end:
            resp = HttpResponse(status=416)
            resp["Content-Range"] = f"bytes */{size}"
            return resp
        with open(path, "rb") as fh:
            fh.seek(start)
            data = fh.read(end - start + 1)
        resp = HttpResponse(data, status=206, content_type=content_type)
        resp["Content-Range"] = f"bytes {start}-{end}/{size}"
        resp["Content-Length"] = str(len(data))
    else:
        resp = FileResponse(open(path, "rb"), content_type=content_type,
                            as_attachment=bool(download_name), filename=download_name or os.path.basename(path))
    resp["Accept-Ranges"] = "bytes"
    resp["Cache-Control"] = "private, max-age=3600"
    return resp


@login_required
@require_GET
def file_view(request, kind, pk):
    if kind == "scene":
        obj = get_object_or_404(Scene, pk=pk, project__user=request.user)
        f, ctype, name = obj.file, "video/mp4", f"{_slug(obj.project.title)}-scene{obj.index + 1:02d}-v{obj.version}.mp4"
    elif kind == "version":
        obj = get_object_or_404(SceneVersion, pk=pk, scene__project__user=request.user)
        f, ctype, name = obj.file, "video/mp4", f"{_slug(obj.scene.project.title)}-scene{obj.scene.index + 1:02d}-v{obj.version}.mp4"
    else:
        obj = get_object_or_404(VideoProject, pk=pk, user=request.user)
        if kind == "final":
            f, ctype, name = obj.final_file, "video/mp4", f"{_slug(obj.title)}-full.mp4"
        elif kind == "music":
            f = obj.music_file
            ext = os.path.splitext(f.name)[1].lstrip(".") if f else "mp3"
            ctype, name = {"mp3": "audio/mpeg", "wav": "audio/wav", "flac": "audio/flac", "ogg": "audio/ogg"}.get(ext, "audio/mpeg"), f"music-{obj.pk}.{ext}"
        elif kind == "frame":
            f, ctype, name = obj.first_frame, "image/png", None
        else:
            raise Http404
    if not f or not os.path.exists(f.path):
        raise Http404
    return _ranged_response(request, f.path, ctype, name if request.GET.get("download") == "1" else None)


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
@login_required
@require_GET
def api_models(request):
    try:
        models = client.get_video_models(force=request.GET.get("refresh") == "1")
    except requests.RequestException as e:
        return JsonResponse({"error": f"โหลดรายชื่อโมเดลไม่ได้: {e}"}, status=502)
    return JsonResponse({
        "models": models,
        "music_models": client.get_music_models(),
        "can_use_paid": request.user.can_use_paid_models,
        "role": request.user.get_role_display(),
    })


@login_required
@require_POST
def api_assist(request):
    try:
        req = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "invalid json"}, status=400)
    if not (req.get("idea") or "").strip():
        return JsonResponse({"error": "กรุณาอธิบายไอเดียวิดีโอก่อน"}, status=400)
    api_key = request.user.profile.api_key
    if not api_key:
        return JsonResponse({"error": "ยังไม่ได้ตั้งค่า OpenRouter API Key"}, status=400)
    try:
        result = client.assist(api_key, _helper_model(request.user), req)
    except (ValueError, requests.RequestException) as e:
        return JsonResponse({"error": str(e)}, status=502)
    return JsonResponse({"ok": True, "helper_model": _helper_model(request.user), **result})


def _bad(msg, status=400):
    return JsonResponse({"error": msg}, status=status)


@login_required
@require_POST
def api_create(request):
    user = request.user
    try:
        data = json.loads(request.POST.get("data") or "{}")
    except json.JSONDecodeError:
        return _bad("ข้อมูลไม่ถูกต้อง")
    if not user.profile.has_api_key:
        return _bad("ยังไม่ได้ตั้งค่า OpenRouter API Key — ไปที่หน้า ตั้งค่า")
    model = client.find_video_model(data.get("model", ""))
    if model is None:
        return _bad("ไม่พบโมเดลวิดีโอนี้")
    if not user.can_use_paid_models:
        return _bad(f"บัญชีประเภท {user.get_role_display()} ใช้ Video Generator ไม่ได้ (ไม่มีโมเดลวิดีโอฟรี) — ติดต่อผู้ดูแลเพื่ออัปเกรดเป็น Pro", 403)

    mode = "series" if data.get("mode") == "series" else "single"
    cfg_in = data.get("config") or {}
    duration = int(cfg_in.get("duration") or 0)
    if duration not in model["durations"]:
        return _bad(f"โมเดลนี้รองรับความยาว {', '.join(map(str, model['durations']))} วินาที")
    aspect = cfg_in.get("aspect_ratio") or ""
    if model["aspect_ratios"] and aspect not in model["aspect_ratios"]:
        return _bad("โมเดลนี้ไม่รองรับสัดส่วนภาพที่เลือก")
    resolution = cfg_in.get("resolution") or ""
    if model["resolutions"] and resolution and resolution not in model["resolutions"]:
        return _bad("โมเดลนี้ไม่รองรับความละเอียดที่เลือก")
    audio_mode = cfg_in.get("audio_mode") if cfg_in.get("audio_mode") in ("silent", "ambient", "voice") else "ambient"
    if not model["audio"] and not model["audio_unknown"]:
        audio_mode = "silent"

    scenes_in = [s for s in (data.get("scenes") or []) if (s.get("prompt") or "").strip()]
    if not scenes_in:
        return _bad("ยังไม่มี prompt — พิมพ์เองหรือกด \"ให้ AI ช่วยคิด Prompt\"")
    if mode == "single":
        scenes_in = scenes_in[:1]
    if len(scenes_in) > settings.VIDEO_MAX_SCENES:
        return _bad(f"สูงสุด {settings.VIDEO_MAX_SCENES} ฉาก")

    config = {
        "aspect_ratio": aspect, "resolution": resolution, "duration": duration,
        "audio_mode": audio_mode, "language": "en" if cfg_in.get("language") == "en" else "th",
        "video_type": str(cfg_in.get("video_type") or "")[:60], "style": str(cfg_in.get("style") or "")[:80],
        "seed": cfg_in.get("seed") if str(cfg_in.get("seed") or "").lstrip("-").isdigit() else None,
        "estimate": cfg_in.get("estimate"),
    }
    if mode == "series":
        config.update({
            "continuity": bool(cfg_in.get("continuity")) and "first_frame" in model["frames"],
            "music": bool(cfg_in.get("music")),
            "music_model": str(cfg_in.get("music_model") or "google/lyria-3-clip-preview")[:200],
            "music_volume": max(0.05, min(1.0, float(cfg_in.get("music_volume") or 0.25))),
        })

    title = (data.get("title") or "").strip() or (data.get("idea") or "").strip()[:60] or "วิดีโอใหม่"
    project = VideoProject.objects.create(
        user=user, mode=mode, title=title[:200], idea=(data.get("idea") or "")[:4000], model=model["id"],
        config=config, style_guide=(data.get("style_guide") or "")[:2000] if mode == "series" else "",
        music_prompt=(data.get("music_prompt") or "")[:2000] if mode == "series" else "",
        status=VideoProject.Status.QUEUED,
    )
    f = request.FILES.get("first_frame")
    if f and "first_frame" in model["frames"]:
        head = f.read(12)
        f.seek(0)
        ext = next((e for magic, e in IMAGE_MAGIC.items() if head.startswith(magic)), None)
        if ext and f.size <= settings.IMAGE_REF_MAX_BYTES:
            project.first_frame.save(f"first_frame.{ext}", ContentFile(f.read()), save=True)

    audio_capable = model["audio"] or model["audio_unknown"]
    for i, s in enumerate(scenes_in):
        scene = Scene(project=project, index=i, prompt=s["prompt"].strip()[:4000],
                      prompt_th=(s.get("prompt_th") or "").strip()[:6000],
                      narration=(s.get("narration") or "").strip()[:1000] if audio_mode == "voice" else "",
                      duration=duration)
        scene.final_prompt = compose_prompt(project, scene, audio_capable and audio_mode != "silent")
        scene.save()
    return JsonResponse({"ok": True, "id": project.pk, "url": reverse("videogen:project", args=[project.pk])})


def _project_json(p: VideoProject) -> dict:
    scenes = list(p.scenes.all())
    done = sum(1 for s in scenes if s.status == Scene.Status.COMPLETED)
    return {
        "id": p.pk, "title": p.title, "status": p.status, "status_label": p.get_status_display(),
        "is_active": p.is_active, "error": p.error, "cost_total": p.cost_total,
        "progress": round(done / len(scenes) * 100) if scenes else 0, "done": done, "total": len(scenes),
        "final_url": reverse("videogen:file", args=["final", p.pk]) if p.final_file else None,
        "music_url": reverse("videogen:file", args=["music", p.pk]) if p.music_file else None,
        "url": reverse("videogen:project", args=[p.pk]),
        "scenes": [{
            "id": s.pk, "index": s.index, "status": s.status, "status_label": s.get_status_display(),
            "error": s.error, "cost": s.cost,
            "url": reverse("videogen:file", args=["scene", s.pk]) if s.file else None,
        } for s in scenes],
    }


@login_required
@require_GET
def api_status(request, pk):
    p = get_object_or_404(VideoProject, pk=pk, user=request.user)
    if not p.is_active and not p.seen:
        p.seen = True
        p.save(update_fields=["seen"])
    return JsonResponse(_project_json(p))


@login_required
@require_GET
def api_badge(request):
    qs = VideoProject.objects.filter(user=request.user)
    finished = qs.filter(seen=False, status__in=["completed", "partial", "failed"]).order_by("-completed_at")[:5]
    return JsonResponse({
        "active": qs.filter(status__in=VideoProject.ACTIVE).count(),
        "unseen": [{"id": p.pk, "title": p.title, "status": p.status, "status_label": p.get_status_display(),
                    "url": reverse("videogen:project", args=[p.pk])} for p in finished],
    })


@login_required
@require_POST
def api_cancel(request, pk):
    p = get_object_or_404(VideoProject, pk=pk, user=request.user)
    if p.is_active:
        p.scenes.exclude(status__in=[Scene.Status.COMPLETED, Scene.Status.FAILED]).update(status=Scene.Status.CANCELLED)
        p.status = VideoProject.Status.CANCELLED
        p.seen = True
        p.save()
    return JsonResponse({"ok": True})


@login_required
@require_POST
def api_retry(request, pk):
    p = get_object_or_404(VideoProject, pk=pk, user=request.user)
    if p.is_active:
        return _bad("งานนี้กำลังทำงานอยู่")
    n = p.scenes.filter(status__in=[Scene.Status.FAILED, Scene.Status.CANCELLED]).update(
        status=Scene.Status.PENDING, attempts=0, error="", job_id="", next_poll_at=None)
    if not n and p.status != VideoProject.Status.PARTIAL:
        return _bad("ไม่มีฉากที่ต้องลองใหม่")
    p.status, p.error, p.seen = VideoProject.Status.QUEUED, "", False
    p.save()
    return JsonResponse({"ok": True})


@login_required
@require_POST
def api_delete(request, pk):
    p = get_object_or_404(VideoProject, pk=pk, user=request.user)
    p.delete()
    return JsonResponse({"ok": True, "url": reverse("videogen:index")})


@login_required
@require_POST
def api_rename(request, pk):
    p = get_object_or_404(VideoProject, pk=pk, user=request.user)
    try:
        title = (json.loads(request.body or b"{}").get("title") or "").strip()
    except json.JSONDecodeError:
        title = ""
    if not title:
        return _bad("ชื่อว่าง")
    p.title = title[:200]
    p.save(update_fields=["title"])
    return JsonResponse({"ok": True, "title": p.title})


# ---------------------------------------------------------------------------
# ดาวน์โหลดทั้งหมดเป็น ZIP (วิดีโอรวม + ทุกฉาก + เพลง + prompt)
# ---------------------------------------------------------------------------
@login_required
@require_GET
def download_zip(request, pk):
    p = get_object_or_404(VideoProject, pk=pk, user=request.user)
    scenes = list(p.scenes.all())
    base = _slug(p.title)
    tmp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
    tmp.close()
    lines = [f"{p.title}", f"โมเดล: {p.model}", f"การตั้งค่า: {json.dumps(p.config, ensure_ascii=False)}", ""]
    if p.style_guide:
        lines += ["Style guide:", p.style_guide, ""]
    with zipfile.ZipFile(tmp.name, "w", compression=zipfile.ZIP_STORED) as z:  # mp4 บีบอัดอยู่แล้ว
        if p.final_file and os.path.exists(p.final_file.path):
            z.write(p.final_file.path, f"{base}-full.mp4")
        for s in scenes:
            lines += [f"ฉาก {s.index + 1} (v{s.version}, {s.duration}s) — {s.get_status_display()}", s.prompt]
            if s.narration:
                lines.append(f"บทพูด: {s.narration}")
            lines.append("")
            if s.file and os.path.exists(s.file.path):
                z.write(s.file.path, f"scenes/scene{s.index + 1:02d}.mp4")
        if p.music_file and os.path.exists(p.music_file.path):
            z.write(p.music_file.path, "music" + os.path.splitext(p.music_file.name)[1])
        if p.music_prompt:
            lines += ["Prompt เพลง:", p.music_prompt]
        z.writestr("prompts.txt", "\n".join(lines))

    class _CleanupFile(FileResponse):
        def close(self):
            super().close()
            try:
                os.unlink(tmp.name)
            except OSError:
                pass

    return _CleanupFile(open(tmp.name, "rb"), as_attachment=True, filename=f"{base}.zip", content_type="application/zip")


# ---------------------------------------------------------------------------
# แก้ไขทีละฉาก
# ---------------------------------------------------------------------------
@login_required
@require_POST
def api_assist_scene(request):
    try:
        req = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return _bad("invalid json")
    api_key = request.user.profile.api_key
    if not api_key:
        return _bad("ยังไม่ได้ตั้งค่า OpenRouter API Key")
    scene_id = req.get("scene_id")
    if scene_id:  # จากหน้าผลงาน → ใช้บริบทจากโปรเจกต์จริง
        s = get_object_or_404(Scene, pk=scene_id, project__user=request.user)
        p = s.project
        scenes = list(p.scenes.all())
        cfg = p.config or {}
        req.update({
            "idea": p.idea, "style_guide": p.style_guide, "video_type": cfg.get("video_type"), "style": cfg.get("style"),
            "audio_mode": cfg.get("audio_mode"), "language": cfg.get("language", "th"), "duration": s.duration,
            "index": s.index, "total": len(scenes),
            "prev_prompt": scenes[s.index - 1].prompt if s.index > 0 else "",
            "next_prompt": scenes[s.index + 1].prompt if s.index + 1 < len(scenes) else "",
        })
    try:
        result = client.assist_scene(api_key, _helper_model(request.user), req)
    except (ValueError, requests.RequestException) as e:
        return JsonResponse({"error": str(e)}, status=502)
    return JsonResponse({"ok": True, **result})


@login_required
@require_POST
def api_scene_regenerate(request, pk):
    s = get_object_or_404(Scene, pk=pk, project__user=request.user)
    p = s.project
    if p.is_active:
        return _bad("งานนี้กำลังทำงานอยู่ — รอให้เสร็จก่อนแล้วค่อยแก้ไขฉาก")
    if not request.user.profile.has_api_key:
        return _bad("ยังไม่ได้ตั้งค่า OpenRouter API Key")
    try:
        body = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return _bad("invalid json")
    prompt = (body.get("prompt") or "").strip()
    if not prompt:
        return _bad("prompt ว่าง")
    model = client.find_video_model(p.model)
    audio_mode = (p.config or {}).get("audio_mode", "ambient")
    audio_capable = bool(model and (model["audio"] or model["audio_unknown"])) and audio_mode != "silent"

    if s.file or s.job_id:  # เก็บเวอร์ชันเดิมไว้ในประวัติ
        SceneVersion.objects.create(scene=s, version=s.version, prompt=s.prompt, prompt_th=s.prompt_th, narration=s.narration,
                                    final_prompt=s.final_prompt, file=s.file.name if s.file else "", cost=s.cost,
                                    created_at=s.completed_at or s.submitted_at or p.created_at)
        s.version += 1
    s.prompt_th = (body.get("prompt_th") or "").strip()[:6000] if prompt != s.prompt else s.prompt_th
    s.prompt = prompt[:4000]
    s.narration = (body.get("narration") or "").strip()[:1000] if audio_mode == "voice" else ""
    s.final_prompt = compose_prompt(p, s, audio_capable)
    s.file = None  # ไฟล์เดิมย้ายไปอยู่ในประวัติแล้ว (ไม่ลบ)
    s.status, s.job_id, s.attempts, s.error, s.cost = Scene.Status.PENDING, "", 0, "", None
    s.next_poll_at = s.submitted_at = s.completed_at = None
    s.save()
    p.status, p.error, p.seen, p.completed_at = VideoProject.Status.QUEUED, "", False, None
    p.save()
    return JsonResponse({"ok": True})


@login_required
@require_POST
def api_scene_restore(request, pk):
    v = get_object_or_404(SceneVersion, pk=pk, scene__project__user=request.user)
    s, p = v.scene, v.scene.project
    if p.is_active:
        return _bad("งานนี้กำลังทำงานอยู่ — รอให้เสร็จก่อน")
    if not v.file:
        return _bad("เวอร์ชันนี้ไม่มีไฟล์วิดีโอ")
    # สลับ: เวอร์ชันปัจจุบันกลายเป็นประวัติ เวอร์ชันที่เลือกกลับมาเป็นปัจจุบัน
    cur = {"version": s.version, "prompt": s.prompt, "prompt_th": s.prompt_th, "narration": s.narration, "final_prompt": s.final_prompt,
           "file": s.file.name if s.file else "", "cost": s.cost, "created_at": s.completed_at or p.created_at}
    s.version, s.prompt, s.prompt_th, s.narration, s.final_prompt, s.file, s.cost = (
        v.version, v.prompt, v.prompt_th, v.narration, v.final_prompt, v.file.name, v.cost)
    s.status, s.error, s.completed_at = Scene.Status.COMPLETED, "", v.created_at
    s.save()
    if cur["file"] or cur["prompt"]:
        SceneVersion.objects.filter(pk=v.pk).update(**cur)
    else:
        SceneVersion.objects.filter(pk=v.pk).delete()
    if p.mode == VideoProject.Mode.SERIES:
        p.status = VideoProject.Status.RUNNING  # worker จะรวมคลิปใหม่ให้
    p.seen = False
    p.save()
    return JsonResponse({"ok": True})


def _captions(cfg: dict) -> dict:
    """คำอธิบายสำหรับโพสต์ที่บันทึกไว้ แยกตามภาษา {"th": {...}, "en": {...}, "both": {...}}"""
    captions = dict(cfg.get("captions") or {})
    old = cfg.get("caption")
    if old and old.get("description") and old.get("lang", "th") not in captions:
        captions[old.get("lang", "th")] = old
    return captions


@login_required
@require_POST
def api_assist_description(request):
    try:
        req = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return _bad("invalid json")
    api_key = request.user.profile.api_key
    if not api_key:
        return _bad("ยังไม่ได้ตั้งค่า OpenRouter API Key")
    if req.get("action") not in ("expand", "ideas", "caption"):
        return _bad("action ไม่ถูกต้อง")
    project = None
    if req.get("project_id"):  # คำอธิบายสำหรับโพสต์จากหน้าผลงาน
        project = get_object_or_404(VideoProject, pk=req["project_id"], user=request.user)
        scenes = list(project.scenes.all())
        cfg = project.config or {}
        req.update({
            "mode": project.mode, "title": project.title, "idea": project.idea, "video_type": cfg.get("video_type"),
            "style": cfg.get("style"), "aspect_ratio": cfg.get("aspect_ratio"), "seconds": sum(x.duration for x in scenes),
            "scenes": [(x.narration + " — " if x.narration else "") + x.prompt[:300] for x in scenes],
        })
    try:
        result = client.assist_description(api_key, _helper_model(request.user), req)
    except (ValueError, requests.RequestException) as e:
        return JsonResponse({"error": str(e)}, status=502)
    if project and req["action"] == "caption":
        cfg = project.config or {}
        captions = _captions(cfg)
        captions[result["lang"]] = result
        project.config = {**cfg, "captions": captions, "caption": result}  # caption = ล่าสุด (รองรับข้อมูลเดิม)
        project.save(update_fields=["config"])
    return JsonResponse({"ok": True, **result})


@login_required
@require_POST
def api_translate(request):
    """แปล prompt เป็นภาษาไทย — ถ้าระบุ scene_ids จะบันทึกคำแปลไว้ (ครั้งต่อไปไม่ต้องแปลซ้ำ)"""
    try:
        req = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return _bad("invalid json")
    texts = [str(t) for t in (req.get("texts") or []) if str(t).strip()][:30]
    if not texts:
        return _bad("ไม่มีข้อความ")
    api_key = request.user.profile.api_key
    if not api_key:
        return _bad("ยังไม่ได้ตั้งค่า OpenRouter API Key")
    model = _helper_model(request.user)
    try:
        out = client.translate_th(api_key, model, texts)
    except (ValueError, requests.RequestException) as e:
        logger.warning("translate_th failed (model=%s): %s", model, e)
        return JsonResponse({"error": f"{e} (โมเดล: {model})"}, status=502)
    except Exception as e:  # noqa: BLE001 — ส่งข้อความกลับไปให้หน้าเว็บแสดงแทน error 500
        logger.exception("translate_th crashed (model=%s)", model)
        return JsonResponse({"error": f"{type(e).__name__}: {e} (โมเดล: {model})"}, status=500)
    for sid, text, th in zip(req.get("scene_ids") or [], texts, out):
        if sid:
            Scene.objects.filter(pk=sid, project__user=request.user, prompt=text).update(prompt_th=th)
    for vid, text, th in zip(req.get("version_ids") or [], texts, out):
        if vid:
            SceneVersion.objects.filter(pk=vid, scene__project__user=request.user, prompt=text).update(prompt_th=th)
    return JsonResponse({"ok": True, "translations": out})
