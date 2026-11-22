"""Worker เบื้องหลังสำหรับ Video Generator (Prompt and Leave)

- ผู้ใช้สั่งงานแล้วปิดหน้าเว็บได้ งานถูกเก็บในฐานข้อมูล
- worker วนทำงาน: ส่งฉากไป OpenRouter → ถามสถานะเป็นระยะ → ดาวน์โหลด → (Series) สร้างเพลง + รวมคลิป
- ถ้าปิด server กลางคัน เมื่อเปิดใหม่ worker จะทำต่อจากสถานะเดิม (job บน OpenRouter ยังทำงานต่อ)
"""
import base64
import logging
import os
import tempfile
import threading
import time
from datetime import timedelta

from django.conf import settings
from django.core.files.base import ContentFile, File
from django.db import close_old_connections
from django.utils import timezone

from . import client, media
from .models import Scene, VideoProject

log = logging.getLogger("videogen.worker")

_started = False
_lock = threading.Lock()

TERMINAL = (Scene.Status.COMPLETED, Scene.Status.FAILED, Scene.Status.CANCELLED)
INFLIGHT = (Scene.Status.SUBMITTED, Scene.Status.IN_PROGRESS, Scene.Status.DOWNLOADING)


# ---------------------------------------------------------------------------
# prompt composition
# ---------------------------------------------------------------------------
def compose_prompt(project: VideoProject, scene: Scene, audio_capable: bool) -> str:
    cfg = project.config or {}
    parts = []
    if project.style_guide.strip():
        parts.append(project.style_guide.strip())
    parts.append(scene.prompt.strip())
    if audio_capable:
        mode = cfg.get("audio_mode", "ambient")
        music = bool(cfg.get("music"))
        if mode == "voice" and scene.narration.strip():
            lang = client.LANG_NAME.get(cfg.get("language", "th"), "Thai")
            parts.append(
                f'Audio: {lang}-language voiceover. The narrator speaks clearly in {lang}: "{scene.narration.strip()}". '
                "Subtle natural ambient sound." + (" No background music." if music else "")
            )
        elif mode in ("ambient", "voice"):
            parts.append("Audio: natural ambient sound effects only, no speech, no dialogue" + (", no music." if music else "."))
    return "\n\n".join(parts)


def _data_url_from_path(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    mt = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif"}.get(ext, "image/png")
    with open(path, "rb") as fh:
        return f"data:{mt};base64,{base64.b64encode(fh.read()).decode()}"


# ---------------------------------------------------------------------------
# scene steps
# ---------------------------------------------------------------------------
def _submit_scene(project: VideoProject, scene: Scene, model: dict | None, prev: Scene | None, api_key: str):
    cfg = project.config or {}
    payload = {"model": project.model, "prompt": scene.final_prompt or scene.prompt, "duration": scene.duration}
    if cfg.get("aspect_ratio"):
        payload["aspect_ratio"] = cfg["aspect_ratio"]
    if cfg.get("resolution"):
        payload["resolution"] = cfg["resolution"]
    if model is None or model.get("audio"):
        payload["generate_audio"] = cfg.get("audio_mode", "ambient") != "silent"
    if cfg.get("seed") not in (None, "") and (model is None or model.get("seed")):
        payload["seed"] = int(cfg["seed"])

    frames = (model or {}).get("frames") or []
    first_frame_url = None
    if scene.index == 0 and project.first_frame and "first_frame" in frames:
        first_frame_url = _data_url_from_path(project.first_frame.path)
    elif cfg.get("continuity") and prev and prev.file and "first_frame" in frames:
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "last.jpg")
            media.last_frame(prev.file.path, out)
            first_frame_url = _data_url_from_path(out)
    if first_frame_url:
        payload["frame_images"] = [{"type": "image_url", "image_url": {"url": first_frame_url}, "frame_type": "first_frame"}]

    scene.attempts += 1
    try:
        data = client.submit(api_key, payload)
    except client.TransientError as e:
        scene.error = str(e)
        if scene.attempts > settings.VIDEO_SUBMIT_RETRIES:
            scene.status = Scene.Status.FAILED
        else:
            scene.next_poll_at = timezone.now() + timedelta(seconds=30 * scene.attempts)
        scene.save()
        return
    except ValueError as e:
        scene.status, scene.error = Scene.Status.FAILED, str(e)
        scene.save()
        return
    scene.job_id = data["id"]
    scene.status = Scene.Status.SUBMITTED
    scene.error = ""
    scene.submitted_at = timezone.now()
    scene.next_poll_at = timezone.now() + timedelta(seconds=settings.VIDEO_POLL_SECONDS)
    scene.save()
    log.info("project %s scene %s submitted job %s", project.pk, scene.index, scene.job_id)


def _poll_scene(project: VideoProject, scene: Scene, api_key: str):
    try:
        data = client.poll(api_key, scene.job_id)
    except client.TransientError as e:
        scene.error = f"ถามสถานะไม่สำเร็จ (จะลองใหม่): {e}"
        scene.next_poll_at = timezone.now() + timedelta(seconds=settings.VIDEO_POLL_SECONDS * 2)
        scene.save(update_fields=["error", "next_poll_at"])
        return
    except ValueError as e:
        scene.status, scene.error = Scene.Status.FAILED, str(e)
        scene.save()
        return

    status = data.get("status")
    usage = data.get("usage") or {}
    if usage.get("cost") is not None:
        scene.cost = float(usage["cost"])
    if status in ("pending", "queued"):
        scene.status = Scene.Status.SUBMITTED
    elif status in ("in_progress", "processing", "running"):
        scene.status = Scene.Status.IN_PROGRESS
    elif status in ("completed", "succeeded"):
        scene.status = Scene.Status.DOWNLOADING
        scene.save(update_fields=["status", "cost"])
        try:
            with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
                tmp_path = tmp.name
            client.download(api_key, scene.job_id, tmp_path, data)
            with open(tmp_path, "rb") as fh:
                scene.file.save(f"scene_{scene.index + 1:02d}.mp4", File(fh), save=False)
            os.unlink(tmp_path)
        except client.TransientError as e:
            scene.status = Scene.Status.IN_PROGRESS  # ลองดาวน์โหลดใหม่รอบหน้า
            scene.error = str(e)
            scene.next_poll_at = timezone.now() + timedelta(seconds=settings.VIDEO_POLL_SECONDS)
            scene.save()
            return
        scene.status = Scene.Status.COMPLETED
        scene.error = ""
        scene.completed_at = timezone.now()
    elif status in ("failed", "cancelled", "expired"):
        err = data.get("error")
        msg = err.get("message") if isinstance(err, dict) else (err or f"งาน {status}")
        scene.status, scene.error = Scene.Status.FAILED, str(msg)
    scene.next_poll_at = timezone.now() + timedelta(seconds=settings.VIDEO_POLL_SECONDS)
    scene.save()


# ---------------------------------------------------------------------------
# project steps
# ---------------------------------------------------------------------------
def _finalize(project: VideoProject, scenes: list[Scene], api_key: str):
    done = [s for s in scenes if s.status == Scene.Status.COMPLETED and s.file]
    from django.db.models import Sum

    from .models import SceneVersion

    old = SceneVersion.objects.filter(scene__project=project).aggregate(c=Sum("cost"))["c"] or 0
    project.cost_total = round(sum(s.cost or 0 for s in scenes) + old, 4)  # รวมค่าใช้จ่ายของเวอร์ชันเก่าด้วย
    if not done:
        project.status = VideoProject.Status.FAILED
        project.error = next((s.error for s in scenes if s.error), "ทุกฉากล้มเหลว")
        project.completed_at = timezone.now()
        project.save()
        return

    all_ok = len(done) == len(scenes)
    if project.mode == VideoProject.Mode.SERIES:
        cfg = project.config or {}
        music_path = None
        if cfg.get("music") and project.music_prompt.strip():
            if not project.music_file:
                project.status = VideoProject.Status.MUSIC
                project.save(update_fields=["status", "updated_at"])
                try:
                    total = sum(s.duration for s in done)
                    prompt = (f"{project.music_prompt.strip()}\nInstrumental background music only, no vocals. "
                              f"Length about {total} seconds.")
                    data, ext = client.generate_music(api_key, cfg.get("music_model") or "google/lyria-3-clip-preview", prompt)
                    project.music_file.save(f"music.{ext}", ContentFile(data), save=False)
                except Exception as e:  # noqa: BLE001 — เพลงล้มเหลวไม่ควรทำให้ทั้งงานล้ม
                    log.warning("music failed: %s", e)
                    project.error = f"สร้างเพลงประกอบไม่สำเร็จ (รวมคลิปโดยไม่มีเพลง): {e}"
            if project.music_file:
                music_path = project.music_file.path

        project.status = VideoProject.Status.STITCHING
        project.save()
        try:
            with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
                out = tmp.name
            media.stitch([s.file.path for s in done], out, music_path, float(cfg.get("music_volume", 0.25)))
            with open(out, "rb") as fh:
                if project.final_file:
                    project.final_file.delete(save=False)
                project.final_file.save("final.mp4", File(fh), save=False)
            os.unlink(out)
        except Exception as e:  # noqa: BLE001
            log.exception("stitch failed")
            project.error = (project.error + "\n" if project.error else "") + str(e)
            all_ok = False

    if all_ok and (project.mode == VideoProject.Mode.SINGLE or project.final_file):
        project.status = VideoProject.Status.COMPLETED
    else:
        project.status = VideoProject.Status.PARTIAL
        if not project.error:
            failed = [s for s in scenes if s.status != Scene.Status.COMPLETED]
            project.error = f"มี {len(failed)} ฉากที่สร้างไม่สำเร็จ — กด \"ลองฉากที่ล้มเหลวใหม่\" ได้"
    project.completed_at = timezone.now()
    project.seen = False
    project.save()
    log.info("project %s finished: %s", project.pk, project.status)


def process_project(project: VideoProject):
    api_key = project.user.profile.api_key
    if not api_key:
        project.status, project.error = VideoProject.Status.FAILED, "ไม่มี OpenRouter API Key"
        project.save()
        return
    if project.status == VideoProject.Status.QUEUED:
        project.status = VideoProject.Status.RUNNING
        project.save(update_fields=["status", "updated_at"])

    model = client.find_video_model(project.model)
    scenes = list(project.scenes.all())
    now = timezone.now()

    for s in scenes:
        if s.status in INFLIGHT and s.job_id and (s.next_poll_at is None or s.next_poll_at <= now):
            _poll_scene(project, s, api_key)

    continuity = project.mode == VideoProject.Mode.SERIES and (project.config or {}).get("continuity")
    inflight = sum(1 for s in scenes if s.status in INFLIGHT)
    for i, s in enumerate(scenes):
        if s.status != Scene.Status.PENDING or (s.next_poll_at and s.next_poll_at > now):
            continue
        prev = scenes[i - 1] if i > 0 else None
        if continuity:
            if inflight or (prev and prev.status not in TERMINAL):
                break
        elif inflight >= settings.VIDEO_MAX_CONCURRENT:
            break
        _submit_scene(project, s, model, prev if (prev and prev.status == Scene.Status.COMPLETED) else None, api_key)
        if s.status == Scene.Status.SUBMITTED:
            inflight += 1

    project.refresh_from_db(fields=["status"])
    if project.status == VideoProject.Status.CANCELLED:
        return
    if all(s.status in TERMINAL for s in scenes):
        _finalize(project, scenes, api_key)


def tick():
    close_old_connections()
    for project in VideoProject.objects.filter(status__in=VideoProject.ACTIVE).select_related("user"):
        try:
            process_project(project)
        except Exception as e:  # noqa: BLE001
            log.exception("project %s crashed", project.pk)
            VideoProject.objects.filter(pk=project.pk).update(error=f"worker error: {e}")


def run_forever(stop_event: threading.Event | None = None):
    log.warning("Video worker started (tick=%ss, poll=%ss)", settings.VIDEO_WORKER_TICK, settings.VIDEO_POLL_SECONDS)
    # งานที่ค้างสถานะ "กำลังรวมคลิป/สร้างเพลง" ตอนปิด server → ให้ทำใหม่
    VideoProject.objects.filter(status__in=[VideoProject.Status.STITCHING, VideoProject.Status.MUSIC]).update(
        status=VideoProject.Status.RUNNING)
    Scene.objects.filter(status=Scene.Status.DOWNLOADING).update(status=Scene.Status.IN_PROGRESS)
    while not (stop_event and stop_event.is_set()):
        try:
            tick()
        except Exception:  # noqa: BLE001
            log.exception("worker tick failed")
        time.sleep(settings.VIDEO_WORKER_TICK)


def start_background_worker():
    global _started
    with _lock:
        if _started:
            return
        _started = True
    t = threading.Thread(target=run_forever, name="video-worker", daemon=True)
    t.start()
