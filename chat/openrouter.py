"""OpenRouter client — รายชื่อโมเดล, ตรวจ API Key, และแชทแบบ streaming"""
import json
import logging

import requests
from django.conf import settings
from django.core.cache import cache

log = logging.getLogger(__name__)

MODELS_CACHE_KEY = "openrouter:models:v1"


def _headers(api_key: str | None = None) -> dict:
    h = {
        "HTTP-Referer": settings.OPENROUTER_APP_URL,
        "X-Title": settings.OPENROUTER_APP_TITLE,
        "Content-Type": "application/json",
    }
    if api_key:
        h["Authorization"] = f"Bearer {api_key}"
    return h


def _to_float(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _normalize(m: dict) -> dict:
    pricing = m.get("pricing") or {}
    prompt = _to_float(pricing.get("prompt"))
    completion = _to_float(pricing.get("completion"))
    variable = prompt < 0 or completion < 0  # เช่น openrouter/auto ราคาขึ้นกับโมเดลที่ถูกเลือก
    is_free = (not variable) and prompt == 0 and completion == 0
    arch = m.get("architecture") or {}
    model_id = m.get("id", "")
    return {
        "id": model_id,
        "name": m.get("name") or model_id,
        "provider": model_id.split("/")[0] if "/" in model_id else "",
        "description": (m.get("description") or "")[:300],
        "context_length": m.get("context_length") or 0,
        "created": m.get("created") or 0,
        # ราคา USD ต่อ 1 ล้าน tokens
        "prompt_price": round(prompt * 1_000_000, 4) if not variable else None,
        "completion_price": round(completion * 1_000_000, 4) if not variable else None,
        "is_free": is_free,
        "is_variable": variable,
        "input_modalities": arch.get("input_modalities") or [],
    }


def get_models(force: bool = False) -> list[dict]:
    """ดึงรายชื่อโมเดลจาก OpenRouter (ไม่ต้องใช้ API Key) และแคชไว้"""
    if not force:
        cached = cache.get(MODELS_CACHE_KEY)
        if cached is not None:
            return cached
    resp = requests.get(f"{settings.OPENROUTER_BASE_URL}/models", headers=_headers(), timeout=20)
    resp.raise_for_status()
    models = [_normalize(m) for m in resp.json().get("data", [])]
    cache.set(MODELS_CACHE_KEY, models, settings.OPENROUTER_MODELS_CACHE_SECONDS)
    return models


def find_model(model_id: str) -> dict | None:
    try:
        for m in get_models():
            if m["id"] == model_id:
                return m
    except requests.RequestException:
        pass
    return None


def is_free_model(model_id: str) -> bool:
    m = find_model(model_id)
    if m is not None:
        return m["is_free"]
    return model_id.endswith(":free")


def check_key(api_key: str) -> tuple[bool, dict]:
    try:
        resp = requests.get(f"{settings.OPENROUTER_BASE_URL}/key", headers=_headers(api_key), timeout=15)
    except requests.RequestException as e:
        return False, {"message": f"เชื่อมต่อ OpenRouter ไม่ได้: {e}"}
    if resp.status_code != 200:
        return False, {"message": _error_message(resp) or "API Key ไม่ถูกต้อง"}
    data = resp.json().get("data", {})
    return True, {
        "message": "API Key ใช้งานได้",
        "label": data.get("label"),
        "usage": data.get("usage"),
        "limit": data.get("limit"),
        "limit_remaining": data.get("limit_remaining"),
        "is_free_tier": data.get("is_free_tier"),
    }


FRIENDLY_ERRORS = {
    401: "API Key ไม่ถูกต้องหรือถูกยกเลิกแล้ว — ตรวจสอบที่หน้า ตั้งค่า",
    402: "เครดิต OpenRouter ไม่พอ — เติมเครดิตหรือเลือกโมเดลฟรี",
    429: "ถูกจำกัดอัตราการใช้งาน (rate limit) — รอสักครู่แล้วลองใหม่ หรือเปลี่ยนโมเดล",
}


def _error_message(resp: requests.Response) -> str:
    friendly = FRIENDLY_ERRORS.get(resp.status_code)
    detail = _raw_error(resp)
    if friendly:
        return f"{friendly} ({detail})" if detail else friendly
    return detail or f"HTTP {resp.status_code}"


def _raw_error(resp: requests.Response) -> str:
    try:
        err = resp.json().get("error")
        if isinstance(err, dict):
            return err.get("message") or json.dumps(err, ensure_ascii=False)
        if err:
            return str(err)
    except ValueError:
        pass
    return ""


def stream_chat(api_key: str, model: str, messages: list[dict], temperature: float = 0.7):
    """Generator: yield dict events
        {"type": "delta", "content": "..."}
        {"type": "usage", "prompt_tokens": n, "completion_tokens": n}
        {"type": "error", "message": "..."}
    """
    payload = {"model": model, "messages": messages, "stream": True, "temperature": temperature}
    try:
        resp = requests.post(
            f"{settings.OPENROUTER_BASE_URL}/chat/completions",
            headers=_headers(api_key),
            json=payload,
            stream=True,
            timeout=(15, 300),
        )
    except requests.RequestException as e:
        yield {"type": "error", "message": f"เชื่อมต่อ OpenRouter ไม่ได้: {e}"}
        return

    if resp.status_code != 200:
        yield {"type": "error", "message": _error_message(resp)}
        resp.close()
        return

    resp.encoding = "utf-8"  # SSE ไม่ได้ระบุ charset — บังคับ UTF-8 ไม่งั้นภาษาไทยเพี้ยน
    try:
        for line in resp.iter_lines(decode_unicode=True):
            if not line or line.startswith(":"):
                continue  # keep-alive comment เช่น ": OPENROUTER PROCESSING"
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                chunk = json.loads(data)
            except json.JSONDecodeError:
                continue
            if chunk.get("error"):
                err = chunk["error"]
                yield {"type": "error", "message": err.get("message") if isinstance(err, dict) else str(err)}
                break
            for choice in chunk.get("choices") or []:
                delta = (choice.get("delta") or {}).get("content")
                if delta:
                    yield {"type": "delta", "content": delta}
            usage = chunk.get("usage")
            if usage:
                yield {
                    "type": "usage",
                    "prompt_tokens": usage.get("prompt_tokens"),
                    "completion_tokens": usage.get("completion_tokens"),
                    "cost": usage.get("cost"),
                }
    finally:
        resp.close()
