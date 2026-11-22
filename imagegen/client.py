"""OpenRouter Image API — รายชื่อโมเดลสร้างภาพ + ราคา และการสั่ง generate
เอกสาร: https://openrouter.ai/docs/features/multimodal/image-generation
"""
import logging
from concurrent.futures import ThreadPoolExecutor

import requests
from django.conf import settings
from django.core.cache import cache

from chat.openrouter import _error_message, _headers

log = logging.getLogger(__name__)

IMAGE_MODELS_CACHE_KEY = "openrouter:image-models:v1"
TOKENS_PER_IMAGE_ESTIMATE = 1300  # ใช้ประมาณราคาสำหรับโมเดลที่คิดเงินเป็น token (~1MP)

# พารามิเตอร์ที่หน้าเว็บรองรับ (ตามเอกสาร OpenRouter)
ALLOWED_PARAMS = {"aspect_ratio", "resolution", "size", "quality", "output_format", "background",
                  "output_compression", "n", "seed"}


def _origin() -> str:
    base = settings.OPENROUTER_BASE_URL
    return base.split("/api/")[0] if "/api/" in base else base


def _price_from_endpoints(endpoints: list[dict]) -> dict:
    """หาราคาต่อภาพที่ถูกที่สุดจากทุก provider"""
    best = None
    variants = False
    estimated = False
    all_zero = True
    for ep in endpoints:
        per_image = []
        per_token = []
        for p in ep.get("pricing") or []:
            cost = p.get("cost_usd")
            if cost is None:
                continue
            if cost > 0:
                all_zero = False
            if p.get("billable") != "output_image":
                continue
            if p.get("unit") == "image":
                per_image.append(cost)
            elif p.get("unit") == "megapixel":
                per_image.append(cost)  # ~1MP ต่อภาพ 1K
            elif p.get("unit") == "token":
                per_token.append(cost * TOKENS_PER_IMAGE_ESTIMATE)
            elif p.get("unit") == "request":
                per_image.append(cost)
        if len(set(per_image)) > 1:
            variants = True
        if per_image:
            price, est = min(per_image), False
        elif per_token:
            price, est = min(per_token), True
        else:
            continue
        if best is None or price < best:
            best, estimated = price, est
    return {"price": best, "price_variants": variants, "price_estimated": estimated, "is_free": best == 0 and all_zero}


def _fetch_endpoints(model: dict) -> list[dict]:
    path = model.get("endpoints") or f"/api/v1/images/models/{model['id']}/endpoints"
    try:
        r = requests.get(_origin() + path, headers=_headers(), timeout=20)
        r.raise_for_status()
        return r.json().get("endpoints") or []
    except (requests.RequestException, ValueError) as e:
        log.warning("image endpoints %s: %s", model.get("id"), e)
        return []


def _normalize(m: dict, endpoints: list[dict]) -> dict:
    params = {k: v for k, v in (m.get("supported_parameters") or {}).items()}
    refs = params.pop("input_references", None) or {"min": 0, "max": 0}
    model_id = m.get("id", "")
    arch = m.get("architecture") or {}
    return {
        "id": model_id,
        "name": m.get("name") or model_id,
        "provider": model_id.split("/")[0] if "/" in model_id else "",
        "description": (m.get("description") or "")[:300],
        "created": m.get("created") or 0,
        "input_modalities": arch.get("input_modalities") or [],
        "params": {k: v for k, v in params.items() if k in ALLOWED_PARAMS},
        "refs_min": refs.get("min", 0) or 0,
        "refs_max": refs.get("max", 0) or 0,
        "providers": [e.get("provider_name") for e in endpoints if e.get("provider_name")],
        **_price_from_endpoints(endpoints),
    }


def get_image_models(force: bool = False) -> list[dict]:
    if not force:
        cached = cache.get(IMAGE_MODELS_CACHE_KEY)
        if cached is not None:
            return cached
    r = requests.get(f"{settings.OPENROUTER_BASE_URL}/images/models", headers=_headers(), timeout=20)
    r.raise_for_status()
    raw = r.json().get("data", [])
    with ThreadPoolExecutor(max_workers=12) as ex:
        endpoints = list(ex.map(_fetch_endpoints, raw))
    models = [_normalize(m, eps) for m, eps in zip(raw, endpoints)]
    cache.set(IMAGE_MODELS_CACHE_KEY, models, settings.OPENROUTER_MODELS_CACHE_SECONDS)
    return models


def find_image_model(model_id: str) -> dict | None:
    try:
        return next((m for m in get_image_models() if m["id"] == model_id), None)
    except requests.RequestException:
        return None


def clean_params(model: dict, raw: dict) -> dict:
    """เก็บเฉพาะพารามิเตอร์ที่โมเดลรองรับ และค่าอยู่ในช่วงที่อนุญาต"""
    out = {}
    spec = model.get("params") or {}
    for key, value in (raw or {}).items():
        if key not in spec or value in (None, ""):
            continue
        d = spec[key]
        t = d.get("type")
        if t == "enum":
            if str(value) in [str(v) for v in d.get("values", [])]:
                out[key] = value
        elif t == "range":
            try:
                num = int(value)
            except (TypeError, ValueError):
                continue
            lo, hi = d.get("min"), d.get("max")
            if (lo is None or num >= lo) and (hi is None or num <= hi):
                out[key] = num
        elif t == "boolean":
            out[key] = bool(value)
        else:  # seed, size — ไม่มีข้อจำกัดชัดเจน
            if key == "seed":
                try:
                    out[key] = int(value)
                except (TypeError, ValueError):
                    pass
            else:
                out[key] = str(value)[:40]
    return out


def generate(api_key: str, model: str, prompt: str, params: dict, references: list[str]) -> tuple[bool, dict]:
    """references = list ของ data URL (data:image/png;base64,...)"""
    payload = {"model": model, "prompt": prompt, **params}
    if references:
        payload["input_references"] = [{"type": "image_url", "image_url": {"url": u}} for u in references]
    try:
        r = requests.post(
            f"{settings.OPENROUTER_BASE_URL}/images",
            headers=_headers(api_key),
            json=payload,
            timeout=(15, settings.IMAGE_GENERATE_TIMEOUT),
        )
    except requests.Timeout:
        return False, {"message": "โมเดลใช้เวลานานเกินไป (timeout) — ลองใหม่หรือเลือกโมเดลที่เร็วกว่า"}
    except requests.RequestException as e:
        return False, {"message": f"เชื่อมต่อ OpenRouter ไม่ได้: {e}"}
    if r.status_code != 200:
        msg = _error_message(r)
        if r.status_code == 502:
            msg = f"สร้างภาพไม่สำเร็จ (ไม่ถูกคิดเงิน) — {msg}"
        return False, {"message": msg}
    try:
        data = r.json()
    except ValueError:
        return False, {"message": "OpenRouter ตอบกลับไม่ใช่ JSON"}
    images = [
        {"b64": item.get("b64_json"), "media_type": item.get("media_type") or "image/png"}
        for item in data.get("data") or []
        if item.get("b64_json")
    ]
    if not images:
        return False, {"message": "โมเดลไม่ได้ส่งภาพกลับมา — ลองปรับ prompt หรือเปลี่ยนโมเดล"}
    usage = data.get("usage") or {}
    return True, {"images": images, "cost": usage.get("cost")}
