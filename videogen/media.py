"""ffmpeg helpers — ตรวจไฟล์, ดึงเฟรมสุดท้าย, รวมคลิป + ผสมเพลงประกอบ"""
import logging
import re
import shutil
import subprocess

from django.conf import settings

log = logging.getLogger(__name__)


class FFmpegMissing(RuntimeError):
    pass


def ffmpeg_exe() -> str:
    if settings.FFMPEG_BINARY:
        return settings.FFMPEG_BINARY
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001
        pass
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    raise FFmpegMissing("ไม่พบ ffmpeg — รัน `pip install imageio-ffmpeg` หรือติดตั้ง ffmpeg ให้อยู่ใน PATH")


def _run(args: list[str], timeout=900) -> subprocess.CompletedProcess:
    kwargs = {}
    if hasattr(subprocess, "CREATE_NO_WINDOW"):  # Windows: ไม่ต้องเด้งหน้าต่าง console
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    return subprocess.run([ffmpeg_exe(), "-hide_banner", *args], capture_output=True, timeout=timeout, **kwargs)


def probe(path: str) -> dict:
    """อ่านข้อมูลไฟล์จาก stderr ของ `ffmpeg -i` (imageio-ffmpeg ไม่มี ffprobe)"""
    p = _run(["-i", path], timeout=60)
    err = p.stderr.decode("utf-8", "replace")
    info = {"width": None, "height": None, "has_audio": "Audio:" in err, "duration": None}
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", err)
    if m:
        h, mi, s = m.groups()
        info["duration"] = int(h) * 3600 + int(mi) * 60 + float(s)
    m = re.search(r"Video:.*?\s(\d{2,5})x(\d{2,5})[\s,]", err)
    if m:
        info["width"], info["height"] = int(m.group(1)), int(m.group(2))
    return info


def last_frame(video_path: str, out_path: str) -> None:
    p = _run(["-y", "-sseof", "-0.3", "-i", video_path, "-frames:v", "1", "-q:v", "2", out_path], timeout=120)
    if p.returncode != 0:
        # สำรอง: ไล่อ่านทั้งไฟล์แล้วเก็บเฟรมสุดท้าย
        p = _run(["-y", "-i", video_path, "-update", "1", "-q:v", "2", out_path], timeout=300)
        if p.returncode != 0:
            raise RuntimeError("ดึงเฟรมสุดท้ายไม่สำเร็จ: " + p.stderr.decode("utf-8", "replace")[-400:])


def stitch(scene_paths: list[str], out_path: str, music_path: str | None = None, music_volume: float = 0.25, fps: int = 24) -> None:
    infos = [probe(p) for p in scene_paths]
    first = next((i for i in infos if i["width"]), {"width": 1280, "height": 720})
    W, H = first["width"] - first["width"] % 2, first["height"] - first["height"] % 2

    args = ["-y"]
    for p in scene_paths:
        args += ["-i", p]
    music_idx = None
    if music_path:
        music_idx = len(scene_paths)
        args += ["-stream_loop", "-1", "-i", music_path]

    filters, concat_in = [], []
    total = 0.0
    for i, info in enumerate(infos):
        d = info["duration"] or 5.0
        total += d
        filters.append(
            f"[{i}:v]scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=black,"
            f"setsar=1,fps={fps},format=yuv420p,trim=0:{d:.3f},setpts=PTS-STARTPTS[v{i}]"
        )
        if info["has_audio"]:
            filters.append(f"[{i}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,apad,"
                           f"atrim=0:{d:.3f},asetpts=PTS-STARTPTS[a{i}]")
        else:
            filters.append(f"anullsrc=r=48000:cl=stereo,atrim=0:{d:.3f},aformat=sample_fmts=fltp[a{i}]")
        concat_in.append(f"[v{i}][a{i}]")
    filters.append(f"{''.join(concat_in)}concat=n={len(infos)}:v=1:a=1[vout][acat]")
    audio_label = "[acat]"
    if music_idx is not None:
        fade_st = max(0.0, total - 2.0)
        filters.append(
            f"[{music_idx}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,atrim=0:{total:.3f},"
            f"afade=t=in:d=1,afade=t=out:st={fade_st:.3f}:d=2,volume={music_volume:.2f}[mus]"
        )
        filters.append("[acat][mus]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[aout]")
        audio_label = "[aout]"

    args += ["-filter_complex", ";".join(filters), "-map", "[vout]", "-map", audio_label,
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "aac", "-b:a", "192k",
             "-movflags", "+faststart", out_path]
    p = _run(args, timeout=1800)
    if p.returncode != 0:
        raise RuntimeError("รวมคลิปไม่สำเร็จ: " + p.stderr.decode("utf-8", "replace")[-800:])
