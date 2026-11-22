"""OpenRouter Video API + Music (audio output) + AI prompt helper
เอกสาร: https://openrouter.ai/docs/features/multimodal/video-generation
"""
import base64
import json
import logging
import re

import requests
from django.conf import settings
from django.core.cache import cache

from chat.openrouter import _error_message, _headers

log = logging.getLogger(__name__)

VIDEO_MODELS_CACHE_KEY = "openrouter:video-models:v1"
AUDIO_MODELS_CACHE_KEY = "openrouter:audio-models:v1"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
def _normalize(m: dict) -> dict:
    model_id = m.get("id", "")
    durations = sorted({int(d) for d in (m.get("supported_durations") or []) if isinstance(d, (int, float)) and d > 0})
    return {
        "id": model_id,
        "name": m.get("name") or model_id,
        "provider": model_id.split("/")[0] if "/" in model_id else "",
        "description": (m.get("description") or "")[:300],
        "created": m.get("created") or 0,
        "durations": durations,
        "aspect_ratios": m.get("supported_aspect_ratios") or [],
        "resolutions": m.get("supported_resolutions") or [],
        "frames": m.get("supported_frame_images") or [],
        "audio": bool(m.get("generate_audio")),
        "audio_unknown": m.get("generate_audio") is None,
        "seed": bool(m.get("seed")),
        "pricing": m.get("pricing_skus") or {},
    }


def get_video_models(force: bool = False) -> list[dict]:
    """เฉพาะโมเดลที่สร้างวิดีโอจากข้อความได้ (มี supported_durations) — ตัดโมเดล avatar / edit / upscale ออก"""
    if not force:
        cached = cache.get(VIDEO_MODELS_CACHE_KEY)
        if cached is not None:
            return cached
    r = requests.get(f"{settings.OPENROUTER_BASE_URL}/videos/models", headers=_headers(), timeout=20)
    r.raise_for_status()
    models = [_normalize(m) for m in r.json().get("data", [])]
    models = [m for m in models if m["durations"]]
    cache.set(VIDEO_MODELS_CACHE_KEY, models, settings.OPENROUTER_MODELS_CACHE_SECONDS)
    return models


def find_video_model(model_id: str) -> dict | None:
    try:
        return next((m for m in get_video_models() if m["id"] == model_id), None)
    except requests.RequestException:
        return None


def get_music_models(force: bool = False) -> list[dict]:
    if not force:
        cached = cache.get(AUDIO_MODELS_CACHE_KEY)
        if cached is not None:
            return cached
    try:
        r = requests.get(f"{settings.OPENROUTER_BASE_URL}/models", params={"output_modalities": "audio"},
                         headers=_headers(), timeout=20)
        r.raise_for_status()
        data = r.json().get("data", [])
    except (requests.RequestException, ValueError):
        return []
    out = []
    for m in data:
        mid = m.get("id", "")
        desc = (m.get("description") or "").lower()
        if "lyria" in mid or "music" in desc:  # เฉพาะโมเดลสร้างเพลง
            out.append({"id": mid, "name": m.get("name") or mid, "description": (m.get("description") or "")[:200]})
    cache.set(AUDIO_MODELS_CACHE_KEY, out, settings.OPENROUTER_MODELS_CACHE_SECONDS)
    return out


# ---------------------------------------------------------------------------
# Video jobs
# ---------------------------------------------------------------------------
class TransientError(Exception):
    """เครือข่ายล่ม / 5xx / 429 — ลองใหม่ได้"""


def submit(api_key: str, payload: dict) -> dict:
    try:
        r = requests.post(f"{settings.OPENROUTER_BASE_URL}/videos", headers=_headers(api_key), json=payload, timeout=(15, 120))
    except requests.RequestException as e:
        raise TransientError(f"เชื่อมต่อ OpenRouter ไม่ได้: {e}")
    if r.status_code in (429,) or r.status_code >= 500:
        raise TransientError(_error_message(r))
    if r.status_code not in (200, 201, 202):
        raise ValueError(_error_message(r))
    data = r.json()
    if not data.get("id"):
        raise ValueError("OpenRouter ไม่ได้ส่ง job id กลับมา")
    return data


def poll(api_key: str, job_id: str) -> dict:
    try:
        r = requests.get(f"{settings.OPENROUTER_BASE_URL}/videos/{job_id}", headers=_headers(api_key), timeout=30)
    except requests.RequestException as e:
        raise TransientError(str(e))
    if r.status_code == 429 or r.status_code >= 500:
        raise TransientError(_error_message(r))
    if r.status_code != 200:
        raise ValueError(_error_message(r))
    return r.json()


def download(api_key: str, job_id: str, dest_path: str, poll_data: dict | None = None) -> None:
    """ดาวน์โหลดไฟล์วิดีโอลงดิสก์ (stream)"""
    urls = [(f"{settings.OPENROUTER_BASE_URL}/videos/{job_id}/content?index=0", True)]
    for u in (poll_data or {}).get("unsigned_urls") or []:
        urls.append((u, True))
    for u in (poll_data or {}).get("urls") or []:
        urls.append((u if isinstance(u, str) else u.get("url", ""), False))
    last_err = None
    for url, with_auth in urls:
        if not url:
            continue
        try:
            headers = _headers(api_key) if with_auth else {}
            headers.pop("Content-Type", None)
            with requests.get(url, headers=headers, stream=True, timeout=(15, 600)) as r:
                if r.status_code != 200:
                    last_err = _error_message(r)
                    continue
                with open(dest_path, "wb") as fh:
                    for chunk in r.iter_content(chunk_size=1024 * 256):
                        if chunk:
                            fh.write(chunk)
                return
        except requests.RequestException as e:
            last_err = str(e)
    raise TransientError(f"ดาวน์โหลดวิดีโอไม่สำเร็จ: {last_err}")


# ---------------------------------------------------------------------------
# Music (audio output ผ่าน Chat Completions + streaming)
# ---------------------------------------------------------------------------
def _sniff_audio(data: bytes) -> str | None:
    if data[:3] == b"ID3" or (len(data) > 1 and data[0] == 0xFF and (data[1] & 0xE0) == 0xE0):
        return "mp3"
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return "wav"
    if data[:4] == b"fLaC":
        return "flac"
    if data[:4] == b"OggS":
        return "ogg"
    return None


def _pcm16_to_wav(pcm: bytes, rate=24000, channels=1) -> bytes:
    import struct

    byte_rate = rate * channels * 2
    header = b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVEfmt " + struct.pack(
        "<IHHIIHH", 16, 1, channels, rate, byte_rate, channels * 2, 16) + b"data" + struct.pack("<I", len(pcm))
    return header + pcm


def generate_music(api_key: str, model: str, prompt: str) -> tuple[bytes, str]:
    """คืนค่า (bytes, นามสกุลไฟล์)"""
    last_err = "ไม่ทราบสาเหตุ"
    for audio_opt in ({"format": "mp3"}, {"format": "wav"}, None):
        payload = {"model": model, "messages": [{"role": "user", "content": prompt}],
                   "modalities": ["text", "audio"], "stream": True}
        if audio_opt:
            payload["audio"] = audio_opt
        try:
            r = requests.post(f"{settings.OPENROUTER_BASE_URL}/chat/completions", headers=_headers(api_key),
                              json=payload, stream=True, timeout=(15, 300))
        except requests.RequestException as e:
            raise TransientError(str(e))
        if r.status_code == 400:
            last_err = _error_message(r)
            continue
        if r.status_code != 200:
            msg = _error_message(r)
            if r.status_code == 429 or r.status_code >= 500:
                raise TransientError(msg)
            raise ValueError(msg)
        r.encoding = "utf-8"
        parts: list[str] = []
        for line in r.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                chunk = json.loads(data)
            except json.JSONDecodeError:
                continue
            if chunk.get("error"):
                raise ValueError(str(chunk["error"].get("message") if isinstance(chunk["error"], dict) else chunk["error"]))
            for ch in chunk.get("choices") or []:
                for key in ("delta", "message"):
                    audio = (ch.get(key) or {}).get("audio") or {}
                    if audio.get("data"):
                        parts.append(audio["data"])
        r.close()
        if not parts:
            last_err = "โมเดลไม่ได้ส่งเสียงกลับมา"
            continue
        raw = base64.b64decode("".join(parts))
        kind = _sniff_audio(raw)
        if kind:
            return raw, kind
        return _pcm16_to_wav(raw), "wav"
    raise ValueError(f"สร้างเพลงไม่สำเร็จ: {last_err}")


# ---------------------------------------------------------------------------
# AI Prompt helper
# ---------------------------------------------------------------------------
LANG_NAME = {"th": "Thai", "en": "English"}


def _word_budget(seconds: int, lang: str) -> str:
    if lang == "th":
        return f"a short Thai sentence that can be spoken in {seconds} seconds (about {int(seconds * 4.5)} Thai syllables max)"
    return f"at most {max(4, int(seconds * 2.3))} English words"


def _extract_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            return json.loads(m.group(0))
        raise


def _chat_json(api_key: str, model: str, system: str, user: str) -> dict:
    base = {"model": model, "temperature": 0.8,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    last = ""
    for extra in ({"response_format": {"type": "json_object"}}, {}):
        try:
            r = requests.post(f"{settings.OPENROUTER_BASE_URL}/chat/completions", headers=_headers(api_key),
                              json={**base, **extra}, timeout=(15, 180))
        except requests.RequestException as e:
            raise ValueError(f"เชื่อมต่อ OpenRouter ไม่ได้: {e}")
        if r.status_code == 400 and extra:
            last = _error_message(r)
            continue
        if r.status_code != 200:
            raise ValueError(_error_message(r))
        content = ((r.json().get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        try:
            return _extract_json(content)
        except (json.JSONDecodeError, ValueError):
            last = "AI ตอบกลับไม่ใช่ JSON ที่อ่านได้"
            if not extra:
                break
    raise ValueError(last or "AI ช่วยคิด prompt ไม่สำเร็จ")


def assist(api_key: str, helper_model: str, req: dict) -> dict:
    mode = req.get("mode", "single")
    lang = req.get("language", "th")
    audio_mode = req.get("audio_mode", "ambient")
    voice = audio_mode == "voice"
    common = (
        f"Video type: {req.get('video_type') or 'general'}\n"
        f"Visual style: {req.get('style') or 'cinematic, photorealistic'}\n"
        f"Aspect ratio: {req.get('aspect_ratio') or '16:9'}\n"
        f"User idea (may be Thai): {req.get('idea', '').strip()}\n"
    )
    rules = (
        "Write video prompts in English for a text-to-video model. Each prompt describes ONE continuous shot: "
        "subject & appearance, action, setting, camera framing & movement, lighting, colour palette, mood. "
        "Be concrete and visual. Do not mention text overlays, logos of real brands or real celebrities. "
        "Respond with ONLY a JSON object, no markdown."
    )
    if mode == "series":
        n = max(1, min(int(req.get("scene_count") or 1), settings.VIDEO_MAX_SCENES))
        d = int(req.get("scene_duration") or 5)
        narr = (f'"narration": {_word_budget(d, lang)} written in {LANG_NAME[lang]}, voiceover for this scene,'
                if voice else '"narration": "" (empty — no speech),')
        system = (
            f"You are a film director and expert AI video prompt engineer. Plan a {n}-scene video, each scene exactly {d} seconds "
            f"(total {n * d} seconds) with a clear story arc (hook → development → payoff/call to action). {rules}\n"
            "JSON schema: {\"title\": short catchy title in Thai, "
            "\"style_guide\": English, 1-2 sentences fixing the visual style, colour grade and the exact appearance of recurring "
            "characters/products so every scene stays consistent (this text is prepended to every scene), "
            f"\"scenes\": array of exactly {n} objects {{\"prompt\": English 40-90 words, \"prompt_th\": natural Thai translation of that prompt, {narr} \"summary\": one short Thai sentence}}, "
            "\"music_prompt\": English description of instrumental background music (genre, mood, tempo, instruments, no vocals)}"
        )
        user = common + f"Number of scenes: {n}\nSeconds per scene: {d}\nVoiceover: {'yes, ' + LANG_NAME[lang] if voice else 'no'}"
        data = _chat_json(api_key, helper_model, system, user)
        scenes = [s for s in (data.get("scenes") or []) if isinstance(s, dict) and s.get("prompt")]
        return {
            "title": str(data.get("title") or "")[:200],
            "style_guide": str(data.get("style_guide") or ""),
            "music_prompt": str(data.get("music_prompt") or ""),
            "scenes": [{"prompt": str(s.get("prompt", "")), "prompt_th": str(s.get("prompt_th", "")),
                        "narration": str(s.get("narration", "")) if voice else "",
                        "summary": str(s.get("summary", ""))} for s in scenes][:n],
        }

    d = int(req.get("duration") or 5)
    narr = (f'"narration": {_word_budget(d, lang)} written in {LANG_NAME[lang]} (voiceover or line of dialogue),'
            if voice else '"narration": "" (empty — no speech),')
    system = (
        f"You are an expert AI video prompt engineer. Create the best possible prompt for a single {d}-second clip. {rules}\n"
        f"JSON schema: {{\"title\": short Thai title, \"prompt\": English 60-120 words, \"prompt_th\": natural Thai translation of the prompt, {narr} "
        "\"tips\": one short Thai sentence explaining the creative choice}"
    )
    user = common + f"Duration: {d} seconds\nVoice: {'yes, ' + LANG_NAME[lang] if voice else 'no'}"
    data = _chat_json(api_key, helper_model, system, user)
    return {
        "title": str(data.get("title") or "")[:200],
        "prompt": str(data.get("prompt") or ""),
        "prompt_th": str(data.get("prompt_th") or ""),
        "narration": str(data.get("narration") or "") if voice else "",
        "tips": str(data.get("tips") or ""),
    }


def assist_scene(api_key: str, helper_model: str, req: dict) -> dict:
    """ให้ AI เขียน/ปรับ prompt เฉพาะฉากเดียว โดยคำนึงถึงฉากก่อน-หลังและ style guide"""
    lang = req.get("language", "th")
    voice = req.get("audio_mode") == "voice"
    d = int(req.get("duration") or 5)
    idx, total = int(req.get("index") or 0), int(req.get("total") or 1)
    narr = (f'"narration": {_word_budget(d, lang)} written in {LANG_NAME[lang]},' if voice
            else '"narration": "" (empty — no speech),')
    system = (
        "You are a film director and expert AI video prompt engineer. Rewrite the prompt for ONE scene of a video. "
        "Keep it consistent with the style guide and with the neighbouring scenes (continuity of characters, setting, lighting), "
        "and follow the user's change request if given. The prompt must describe one continuous shot in English (40-100 words): "
        "subject, action, setting, camera framing & movement, lighting, mood. No text overlays, real brands or celebrities. "
        f"Respond with ONLY JSON: {{\"prompt\": \"...\", \"prompt_th\": \"natural Thai translation of the prompt\", {narr} \"note\": \"one short Thai sentence describing what you changed\"}}"
    )
    user = (
        f"Video idea: {req.get('idea') or '-'}\n"
        f"Video type / style: {req.get('video_type') or '-'} / {req.get('style') or '-'}\n"
        f"Style guide (prepended to every scene): {req.get('style_guide') or '-'}\n"
        f"This is scene {idx + 1} of {total}, {d} seconds long.\n"
        f"Previous scene prompt: {req.get('prev_prompt') or '(none — this is the first scene)'}\n"
        f"Next scene prompt: {req.get('next_prompt') or '(none — this is the last scene)'}\n"
        f"Current prompt of this scene: {req.get('prompt') or '(empty — write a new one)'}\n"
        f"Current narration: {req.get('narration') or '-'}\n"
        f"User's change request (may be Thai): {req.get('instruction') or '(none — improve it to be more cinematic and specific)'}"
    )
    data = _chat_json(api_key, helper_model, system, user)
    if not data.get("prompt"):
        raise ValueError("AI ไม่ได้ส่ง prompt กลับมา")
    return {"prompt": str(data["prompt"]), "prompt_th": str(data.get("prompt_th") or ""),
            "narration": str(data.get("narration") or "") if voice else "", "note": str(data.get("note") or "")}


CAPTION_LANGS = ("th", "en", "both")  # ภาษาของคำอธิบายสำหรับโพสต์


def assist_description(api_key: str, helper_model: str, req: dict) -> dict:
    """ช่วยคิด description ของวิดีโอ
    action = expand (ขยายไอเดีย) | ideas (เสนอ 3 ไอเดีย) | caption (คำอธิบายสำหรับโพสต์ YouTube/TikTok/Facebook)
    """
    action = req.get("action", "expand")
    mode = "series (multi-scene short film / ad)" if req.get("mode") == "series" else "single clip"
    ctx = (
        f"Format: {mode}, total length about {req.get('seconds') or '?'} seconds, aspect {req.get('aspect_ratio') or '16:9'}\n"
        f"Video type: {req.get('video_type') or '-'}\nVisual style: {req.get('style') or '-'}\n"
        f"Current idea/description (Thai, may be empty or short): {req.get('idea') or '(empty)'}\n"
    )
    if action == "ideas":
        system = ("You are a creative director for short videos. Propose 3 distinctly different, vivid, filmable video concepts "
                  "that fit the format and type (if the user gave an idea, make 3 variations of it). Write in Thai. "
                  "Respond with ONLY JSON: {\"ideas\": [{\"title\": \"short catchy Thai title\", \"description\": \"2-4 Thai sentences: "
                  "subject, setting, what happens, mood/hook\"}, ...3 items]}")
        data = _chat_json(api_key, helper_model, system, ctx)
        ideas = [{"title": str(i.get("title", ""))[:120], "description": str(i.get("description", ""))}
                 for i in (data.get("ideas") or []) if isinstance(i, dict) and i.get("description")][:3]
        if not ideas:
            raise ValueError("AI ไม่ได้เสนอไอเดียกลับมา")
        return {"ideas": ideas}
    if action == "caption":
        lang = req.get("caption_lang") if req.get("caption_lang") in CAPTION_LANGS else "th"
        scenes = req.get("scenes") or []
        ctx += f"Title: {req.get('title') or '-'}\n" + ("Scenes:\n" + "\n".join(f"- {s}" for s in scenes[:24]) if scenes else "")
        if lang == "en":
            system = ("You are a social media copywriter. Write a post description for publishing this video on YouTube / TikTok / Facebook, "
                      "in natural, native-sounding English (the source notes may be Thai — do not translate word for word). "
                      "Respond with ONLY JSON: {\"title\": \"catchy English title (max 70 chars)\", \"description\": \"engaging English description, "
                      "2 short paragraphs with a hook and a call to action, emojis allowed\", \"hashtags\": [\"#...\", 8-12 relevant English tags]}")
        elif lang == "both":
            system = ("You are a social media copywriter. Write a bilingual (Thai + English) post description for publishing this video on "
                      "YouTube / TikTok / Facebook, for both Thai and international viewers. "
                      "Respond with ONLY JSON: {\"title\": \"catchy title: Thai part | English part (max 100 chars)\", "
                      "\"description\": \"a short Thai paragraph with a hook and call to action, then a blank line, then the same message "
                      "written naturally in English (not a literal translation); emojis allowed\", "
                      "\"hashtags\": [\"#...\", 10-14 relevant tags mixing Thai and English]}")
        else:
            system = ("You are a social media copywriter. Write a post description for publishing this video on YouTube / TikTok / Facebook, in Thai. "
                      "Respond with ONLY JSON: {\"title\": \"catchy Thai title (max 70 chars)\", \"description\": \"engaging Thai description, "
                      "2 short paragraphs with a hook and a call to action, emojis allowed\", \"hashtags\": [\"#...\", 8-12 relevant tags mixing Thai and English]}")
        data = _chat_json(api_key, helper_model, system, ctx)
        tags = [t if str(t).startswith("#") else f"#{t}" for t in (data.get("hashtags") or []) if str(t).strip()][:15]
        tags = [re.sub(r"\s+", "", t) for t in tags]
        return {"title": str(data.get("title") or "")[:150], "description": str(data.get("description") or ""),
                "hashtags": tags, "lang": lang}
    system = ("You are a creative director. Expand the user's video idea into a rich, filmable description in Thai (4-6 sentences): "
              "main subject/character with appearance, setting, what happens (beginning → end), mood, key visual moments"
              + (", and the story arc across scenes" if req.get("mode") == "series" else "") +
              ". Keep the user's intent; if the idea is empty, invent a fitting one. Respond with ONLY JSON: {\"description\": \"...\"}")
    data = _chat_json(api_key, helper_model, system, ctx)
    if not data.get("description"):
        raise ValueError("AI ไม่ได้ส่งคำอธิบายกลับมา")
    return {"description": str(data["description"])}



def translate_th(api_key: str, helper_model: str, texts: list[str]) -> list[str]:
    """แปล prompt ภาษาอังกฤษเป็นภาษาไทย (สำหรับไอคอนดูคำแปล)"""
    texts = [t[:4000] for t in texts][:30]
    system = ("Translate each English video-generation prompt into natural, easy-to-read Thai, keeping technical film terms "
              "(e.g. dolly-in, close-up) understandable — add the English term in brackets when helpful. "
              f"Respond with ONLY JSON: {{\"translations\": [exactly {len(texts)} Thai strings in the same order]}}")
    user = "\n\n".join(f"[{i + 1}] {t}" for i, t in enumerate(texts))
    data = _chat_json(api_key, helper_model, system, user)
    raw = data.get("translations") if isinstance(data, dict) else data
    if raw is None and isinstance(data, dict):  # บางโมเดลใช้ชื่อ key อื่น
        raw = next((v for v in data.values() if isinstance(v, (list, str))), None)
    if isinstance(raw, str):
        raw = [raw]
    out = []
    for x in raw or []:
        if isinstance(x, dict):  # เช่น {"thai": "..."} หรือ {"text": "..."}
            x = next((v for k, v in x.items() if isinstance(v, str) and k.lower() in ("thai", "th", "translation", "text")),
                     next((v for v in x.values() if isinstance(v, str)), ""))
        out.append(re.sub(r"^\s*\[\d+\]\s*", "", str(x)).strip())
    if len(out) != len(texts) or not all(out):
        raise ValueError("AI แปลไม่ครบ ลองใหม่อีกครั้ง หรือเปลี่ยนโมเดลเริ่มต้นในหน้าตั้งค่า")
    return out
