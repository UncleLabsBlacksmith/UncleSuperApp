"""Data Analyst engine: เตรียมบริบทข้อมูล → ให้ AI วางแผน (JSON) → คำนวณจริงด้วย docparse.tables → สร้างข้อความสรุป"""
import base64
import json
import logging
import re

import requests
from django.conf import settings

from chat.openrouter import _error_message, _headers
from docparse import tables as tb
from docparse.extract import load_tables

log = logging.getLogger(__name__)


class DataBundle:
    def __init__(self):
        self.tables = {}      # tid -> Table
        self.types = {}       # tid -> [types]
        self.labels = {}      # tid -> "ไฟล์ › ชีต"
        self.profiles = {}    # tid -> profile dict
        self.docs = []        # (name, text)
        self.images = []      # (name, data_url)
        self.notes = []

    @property
    def has_tables(self):
        return bool(self.tables)


def load_bundle(session) -> DataBundle:
    b = DataBundle()
    n = 0
    for f in session.files.all():
        try:
            if f.kind == "table" and f.cache:
                for t in load_tables(f.cache.path):
                    n += 1
                    tid = f"T{n}"
                    b.tables[tid] = t
                    b.types[tid] = tb.infer_types(t)
                    b.labels[tid] = f"{f.original_name} › {t.name}"
                    b.profiles[tid] = tb.profile(t, b.types[tid])
            elif f.kind == "text" and f.cache:
                with open(f.cache.path, encoding="utf-8") as fh:
                    b.docs.append((f.original_name, fh.read()))
            elif f.kind == "image":
                with open(f.file.path, "rb") as fh:
                    b.images.append((f.original_name, f"data:{f.media_type};base64,{base64.b64encode(fh.read()).decode()}"))
        except (OSError, ValueError) as e:
            b.notes.append(f"อ่านไฟล์ {f.original_name} ไม่สำเร็จ: {e}")
    return b


def profiles_text(b: DataBundle) -> str:
    parts = []
    for tid, t in b.tables.items():
        p = b.profiles[tid]
        p = {**p, "name": b.labels[tid]}
        parts.append(tb.profile_text(tid, p, t.rows[:12], t.columns))
    return "\n\n".join(parts)


def docs_text(b: DataBundle, budget: int) -> str:
    if not b.docs:
        return ""
    per = max(2000, budget // len(b.docs))
    out = []
    for name, text in b.docs:
        cut = text[:per]
        note = f"\n…(ตัดเหลือ {per:,} จาก {len(text):,} ตัวอักษร — ถ้าต้องการค้นหาทั้งเอกสาร ใช้หน้า RAG)" if len(text) > per else ""
        out.append(f"=== เอกสาร: {name} ===\n{cut}{note}")
    return "\n\n".join(out)


# ---------------------------------------------------------------------------
def _chat(api_key, model, messages, json_mode=False, timeout=180):
    payload = {"model": model, "messages": messages, "temperature": 0.2}
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    r = requests.post(f"{settings.OPENROUTER_BASE_URL}/chat/completions", headers=_headers(api_key), json=payload,
                      timeout=(15, timeout))
    if r.status_code == 400 and json_mode:
        payload.pop("response_format")
        r = requests.post(f"{settings.OPENROUTER_BASE_URL}/chat/completions", headers=_headers(api_key), json=payload,
                          timeout=(15, timeout))
    if r.status_code != 200:
        raise ValueError(_error_message(r))
    return ((r.json().get("choices") or [{}])[0].get("message") or {}).get("content") or ""


def _parse_json(text: str) -> dict:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        return json.loads(m.group(0)) if m else {}


PLAN_SYSTEM = """You are a senior data analyst. You receive profiles of tabular datasets (table ids like T1, exact column names, types, stats, sample rows) and a user question (often Thai).
Decide which computations best answer the question. The server will execute them on the FULL data — never invent numbers.
Return ONLY a JSON object:
{
 "metrics": [ {"label": "short Thai label", "table": "T1", "column": "<exact column or null for row count>", "agg": "sum|mean|count|min|max|distinct|median", "filters": []} ],
 "charts":  [ {"title": "Thai title", "type": "bar|horizontalBar|line|area|pie|doughnut|scatter", "table": "T1", "x": "<column>", "y": "<numeric column or null to count rows>",
               "agg": "sum|mean|count|min|max|median", "series": "<optional column to split into multiple series or null>",
               "bucket": "none|day|week|month|quarter|year (for date x)", "sort": "x|value_desc|value_asc", "limit": 12, "filters": []} ],
 "tables":  [ {"title": "Thai title", "table": "T1", "group_by": "<column>", "bucket": "none|month|...", "values": [{"column": "<col>", "agg": "sum"}, {"agg": "count"}], "sort": "value_desc|x", "limit": 15} ]
}
filters item: {"column": "<col>", "op": "eq|neq|contains|gt|lt|gte|lte", "value": ...}
Rules: max 4 metrics, 4 charts, 2 tables. Use exact column names. Time series → line/area with x = date column and a bucket that gives 6-30 points. Categories → bar (horizontalBar for long labels), top N with limit. pie/doughnut only for ≤ 6 parts of a whole. Use series only when comparing a few groups. If the question needs no computation (e.g. about document text), return empty lists."""

ANSWER_SYSTEM = """You are "Uncle Data Analyst", an expert data analyst assistant. Answer in the same language as the user (default Thai), using clear Markdown:
- Start with a 1-2 sentence direct answer, then key findings as bullets with concrete numbers, then insights / anomalies, then practical recommendations.
- Numbers about tabular data MUST come from the COMPUTED RESULTS or the dataset profile — never invent or estimate figures that are not given. If something cannot be computed from the data, say so.
- Charts and KPI cards computed by the system are already displayed above your answer — refer to them by title instead of repeating every number.
- For document/image content, summarize, extract and analyse faithfully; cite the file name.
- If a document (not a table) contains numbers worth visualising, you may add a chart using a fenced code block with language "chart" containing JSON:
```chart
{"type": "bar", "title": "...", "labels": ["A", "B"], "datasets": [{"label": "...", "data": [1, 2]}]}
```
(types: bar, horizontalBar, line, area, pie, doughnut). Only use numbers that appear in the documents.
- Keep it concise and well structured; use tables in Markdown when comparing items."""


def plan(api_key, model, b: DataBundle, question: str, history_q: list) -> dict:
    ctx = profiles_text(b)
    prev = ("\nคำถามก่อนหน้า: " + " | ".join(history_q[-3:])) if history_q else ""
    content = _chat(api_key, model, [
        {"role": "system", "content": PLAN_SYSTEM},
        {"role": "user", "content": f"DATASETS:\n{ctx}\n{prev}\nQUESTION: {question}"},
    ], json_mode=True)
    data = _parse_json(content)
    return data if isinstance(data, dict) else {}


def execute(b: DataBundle, spec: dict) -> dict:
    out = {"metrics": [], "charts": [], "tables": [], "errors": []}
    for m in (spec.get("metrics") or [])[:4]:
        try:
            out["metrics"].append(tb.metric(b.tables, m))
        except (ValueError, TypeError, KeyError) as e:
            out["errors"].append(f"metric: {e}")
    for c in (spec.get("charts") or [])[:4]:
        try:
            res = tb.chart(b.tables, b.types, c)
            if res["labels"] or res["type"] == "scatter":
                res["source"] = b.labels.get(c.get("table"), "")
                out["charts"].append(res)
        except (ValueError, TypeError, KeyError) as e:
            out["errors"].append(f"chart: {e}")
    for t in (spec.get("tables") or [])[:2]:
        try:
            out["tables"].append(tb.group_table(b.tables, b.types, t))
        except (ValueError, TypeError, KeyError) as e:
            out["errors"].append(f"table: {e}")
    return out


def results_text(res: dict) -> str:
    lines = []
    for m in res["metrics"]:
        lines.append(f"- KPI \"{m['label']}\": {m['display']}")
    for c in res["charts"]:
        if c["type"] == "scatter":
            lines.append(f"- กราฟ \"{c['title']}\" (scatter {len(c['datasets'][0]['data'])} จุด)")
            continue
        lines.append(f"- กราฟ \"{c['title']}\" ({c['type']}, {c.get('y_label')}):")
        for ds in c["datasets"][:4]:
            pairs = ", ".join(f"{l}={v:,.2f}" if isinstance(v, float) else f"{l}={v}" for l, v in list(zip(c["labels"], ds["data"]))[:30])
            lines.append(f"    [{ds['label']}] {pairs}")
    for t in res["tables"]:
        lines.append(f"- ตาราง \"{t['title']}\" ({t['total_groups']} กลุ่ม):")
        lines.append("    | " + " | ".join(map(str, t["header"])) + " |")
        for r in t["rows"][:20]:
            lines.append("    | " + " | ".join("" if v is None else (f"{v:,.2f}" if isinstance(v, float) else str(v)) for v in r) + " |")
    return "\n".join(lines)


def build_answer_messages(b: DataBundle, res: dict | None, question: str, history: list, use_images: bool) -> list:
    ctx_parts = []
    if b.has_tables:
        ctx_parts.append("DATASET PROFILES:\n" + profiles_text(b))
    if res and (res["metrics"] or res["charts"] or res["tables"]):
        ctx_parts.append("COMPUTED RESULTS (from full data, shown to the user as KPI cards / charts / tables):\n" + results_text(res))
    d = docs_text(b, settings.ANALYST_CONTEXT_CHARS)
    if d:
        ctx_parts.append("DOCUMENTS:\n" + d)
    if b.images and not use_images:
        ctx_parts.append("(มีรูปภาพแนบมา แต่โมเดลที่เลือกไม่รองรับการอ่านรูปภาพ — แจ้งผู้ใช้ให้เลือกโมเดลที่มีป้าย vision)")
    if b.notes:
        ctx_parts.append("NOTES: " + "; ".join(b.notes))
    msgs = [{"role": "system", "content": ANSWER_SYSTEM + "\n\n" + "\n\n".join(ctx_parts)}]
    msgs += history[-8:]
    if use_images and b.images:
        parts = [{"type": "text", "text": question}]
        for name, url in b.images[:6]:
            parts.append({"type": "text", "text": f"(รูปภาพ: {name})"})
            parts.append({"type": "image_url", "image_url": {"url": url}})
        msgs.append({"role": "user", "content": parts})
    else:
        msgs.append({"role": "user", "content": question})
    return msgs
