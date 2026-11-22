"""Engine วิเคราะห์ตาราง (pure Python) — ตรวจชนิดคอลัมน์, สรุปสถิติ, รวมกลุ่มข้อมูลเพื่อทำกราฟ
AI จะส่ง "แผนการวิเคราะห์" (JSON) มา แล้วเราคำนวณจากข้อมูลจริงทุกแถว ไม่ให้ AI เดาตัวเลขเอง
"""
import math
import re
from collections import Counter, defaultdict
from datetime import datetime

AGGS = {"sum", "mean", "avg", "count", "min", "max", "distinct", "median"}
BUCKETS = {"none", "day", "week", "month", "quarter", "year"}
CHART_TYPES = {"bar", "line", "pie", "doughnut", "horizontalBar", "scatter", "area"}

_num_clean = re.compile(r"[,\s฿$€£¥%]|บาท|THB|USD", re.I)
DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d", "%d-%m-%Y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M",
                "%d/%m/%Y %H:%M", "%Y-%m", "%d %b %Y", "%b %Y", "%d.%m.%Y")


def to_number(v):
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return None if isinstance(v, float) and math.isnan(v) else float(v)
    if isinstance(v, datetime):
        return None
    s = str(v).strip()
    if not s:
        return None
    neg = s.startswith("(") and s.endswith(")")
    s = _num_clean.sub("", s.strip("()"))
    try:
        n = float(s)
    except ValueError:
        return None
    return -n if neg else n


def to_date(v):
    if isinstance(v, datetime):
        return v
    if v is None or isinstance(v, (int, float)):
        return None
    s = str(v).strip()
    if not (6 <= len(s) <= 25) or not re.search(r"\d", s):
        return None
    for fmt in DATE_FORMATS:
        try:
            d = datetime.strptime(s, fmt)
        except ValueError:
            continue
        if d.year > 2400:  # ปี พ.ศ.
            d = d.replace(year=d.year - 543)
        return d
    return None


def infer_types(table) -> list:
    types = []
    sample_rows = table.rows[:3000]
    for ci in range(len(table.columns)):
        vals = [r[ci] for r in sample_rows if ci < len(r) and r[ci] is not None]
        if not vals:
            types.append("empty")
            continue
        n_date = sum(1 for v in vals if to_date(v) is not None)
        n_num = sum(1 for v in vals if to_number(v) is not None)
        if n_date >= 0.8 * len(vals):
            types.append("date")
        elif n_num >= 0.8 * len(vals):
            types.append("number")
        else:
            types.append("text")
    return types


def _fmt_num(x):
    if x is None:
        return "—"
    if abs(x) >= 100 or float(x).is_integer():
        return f"{x:,.0f}" if float(x).is_integer() or abs(x) >= 1000 else f"{x:,.2f}"
    return f"{x:,.4g}"


def profile(table, types=None) -> dict:
    types = types or infer_types(table)
    cols = []
    for ci, (name, t) in enumerate(zip(table.columns, types)):
        vals = [r[ci] for r in table.rows if r[ci] is not None]
        info = {"name": name, "type": t, "non_empty": len(vals)}
        if t == "number":
            nums = [n for n in (to_number(v) for v in vals) if n is not None]
            if nums:
                info.update(sum=sum(nums), min=min(nums), max=max(nums), mean=sum(nums) / len(nums))
        elif t == "date":
            ds = [d for d in (to_date(v) for v in vals) if d]
            if ds:
                info.update(min=min(ds).strftime("%Y-%m-%d"), max=max(ds).strftime("%Y-%m-%d"))
        else:
            c = Counter(str(v) for v in vals)
            info.update(distinct=len(c), top=c.most_common(8))
        cols.append(info)
    return {"name": table.name, "rows": len(table.rows), "columns": cols, "truncated": table.truncated}


def profile_text(tid: str, p: dict, sample_rows: list, columns: list) -> str:
    lines = [f"### {tid}: {p['name']} — {p['rows']:,} แถว{' (ตัดเหลือ 200,000 แถว)' if p['truncated'] else ''}", "คอลัมน์:"]
    for c in p["columns"]:
        if c["type"] == "number" and "sum" in c:
            extra = f"sum={_fmt_num(c['sum'])}, mean={_fmt_num(c['mean'])}, min={_fmt_num(c['min'])}, max={_fmt_num(c['max'])}"
        elif c["type"] == "date" and "min" in c:
            extra = f"ช่วง {c['min']} ถึง {c['max']}"
        elif c["type"] == "text":
            top = ", ".join(f"{k} ({v})" for k, v in c.get("top", [])[:6])
            extra = f"{c.get('distinct', 0)} ค่าไม่ซ้ำ; ค่าที่พบบ่อย: {top}"
        else:
            extra = ""
        lines.append(f"- \"{c['name']}\" [{c['type']}] มีค่า {c['non_empty']:,} แถว; {extra}")
    lines.append("ตัวอย่างข้อมูล (CSV):")
    lines.append(",".join(f'"{c}"' for c in columns))
    for r in sample_rows:
        lines.append(",".join("" if v is None else (v.strftime("%Y-%m-%d") if isinstance(v, datetime) else str(v).replace(",", " ")) for v in r))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Filters / aggregation
# ---------------------------------------------------------------------------
def _match(v, op, target):
    if op in ("gt", "lt", "gte", "lte"):
        a, b = to_number(v), to_number(target)
        if a is None or b is None:
            da, db = to_date(v), to_date(target)
            if da is None or db is None:
                return False
            a, b = da, db
        return {"gt": a > b, "lt": a < b, "gte": a >= b, "lte": a <= b}[op]
    sv, st = ("" if v is None else str(v)).strip().lower(), str(target).strip().lower()
    if op == "contains":
        return st in sv
    if op == "neq":
        return sv != st
    if isinstance(target, list):
        return sv in [str(t).strip().lower() for t in target]
    return sv == st


def _filter_rows(table, filters):
    idx = {c: i for i, c in enumerate(table.columns)}
    conds = [(idx[f["column"]], f.get("op", "eq"), f.get("value")) for f in (filters or [])
             if isinstance(f, dict) and f.get("column") in idx]
    if not conds:
        return table.rows
    return [r for r in table.rows if all(_match(r[i], op, val) for i, op, val in conds)]


def _bucket(d: datetime, b: str):
    if b == "year":
        return f"{d.year}"
    if b == "quarter":
        return f"{d.year}-Q{(d.month - 1) // 3 + 1}"
    if b == "month":
        return f"{d.year}-{d.month:02d}"
    if b == "week":
        y, w, _ = d.isocalendar()
        return f"{y}-W{w:02d}"
    return d.strftime("%Y-%m-%d")


def _agg(values: list, agg: str):
    if agg == "count":
        return len(values)
    if agg == "distinct":
        return len(set(map(str, values)))
    nums = [n for n in (to_number(v) for v in values) if n is not None]
    if not nums:
        return None
    if agg == "sum":
        return sum(nums)
    if agg in ("mean", "avg"):
        return sum(nums) / len(nums)
    if agg == "min":
        return min(nums)
    if agg == "max":
        return max(nums)
    if agg == "median":
        s = sorted(nums)
        m = len(s) // 2
        return s[m] if len(s) % 2 else (s[m - 1] + s[m]) / 2
    return None


def _round(v):
    if v is None:
        return None
    return round(v, 4) if isinstance(v, float) else v


def _x_key(v, xtype, bucket):
    if v is None:
        return None
    if xtype == "date" or bucket not in ("none", None):
        d = to_date(v)
        if d is not None:
            return _bucket(d, bucket if bucket in BUCKETS and bucket != "none" else "day")
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def metric(tables: dict, spec: dict) -> dict:
    t = tables.get(spec.get("table"))
    if t is None:
        raise ValueError(f"ไม่พบตาราง {spec.get('table')}")
    agg = spec.get("agg", "sum")
    rows = _filter_rows(t, spec.get("filters"))
    col = spec.get("column")
    if agg == "count" and (not col or col not in t.columns):
        val = len(rows)
    else:
        if col not in t.columns:
            raise ValueError(f"ไม่พบคอลัมน์ {col}")
        ci = t.columns.index(col)
        val = _agg([r[ci] for r in rows if r[ci] is not None], agg if agg in AGGS else "sum")
    return {"label": str(spec.get("label") or f"{agg} {col}")[:60], "value": _round(val),
            "display": _fmt_num(val) if isinstance(val, (int, float)) else "—", "agg": agg, "column": col}


def chart(tables: dict, types: dict, spec: dict) -> dict:
    tid = spec.get("table")
    t = tables.get(tid)
    if t is None:
        raise ValueError(f"ไม่พบตาราง {tid}")
    ctype = spec.get("type") if spec.get("type") in CHART_TYPES else "bar"
    xcol, ycol, scol = spec.get("x"), spec.get("y"), spec.get("series")
    if xcol not in t.columns:
        raise ValueError(f"ไม่พบคอลัมน์ {xcol}")
    agg = spec.get("agg") if spec.get("agg") in AGGS else ("sum" if ycol else "count")
    if not ycol or ycol not in t.columns:
        ycol, agg = None, "count"
    rows = _filter_rows(t, spec.get("filters"))
    xi = t.columns.index(xcol)
    yi = t.columns.index(ycol) if ycol else None
    si = t.columns.index(scol) if scol in t.columns and scol != xcol else None
    ttypes = types.get(tid, [])
    xtype = ttypes[xi] if xi < len(ttypes) else "text"
    bucket = spec.get("bucket") or ("month" if xtype == "date" else "none")
    limit = max(2, min(int(spec.get("limit") or 15), 50))

    if ctype == "scatter":
        pts = []
        for r in rows:
            a, b = to_number(r[xi]), to_number(r[yi]) if yi is not None else None
            if a is not None and b is not None:
                pts.append({"x": a, "y": b})
            if len(pts) >= 800:
                break
        return {"title": spec.get("title") or f"{ycol} vs {xcol}", "type": "scatter", "x_label": xcol, "y_label": ycol,
                "labels": [], "datasets": [{"label": f"{ycol}", "data": pts}]}

    groups = defaultdict(lambda: defaultdict(list))
    for r in rows:
        k = _x_key(r[xi], xtype, bucket)
        if k is None:
            continue
        s = str(r[si]) if si is not None and r[si] is not None else "_"
        groups[s][k].append(r[yi] if yi is not None else 1)

    # จำนวน series สูงสุด 8 (เก็บตัวที่ค่ารวมสูงสุด)
    series_tot = {s: sum((_agg(v, agg) or 0) for v in g.values()) for s, g in groups.items()}
    series = sorted(series_tot, key=lambda s: -series_tot[s])[:8]
    totals = defaultdict(float)
    for s in series:
        for k, v in groups[s].items():
            totals[k] += _agg(v, agg) or 0

    sort = spec.get("sort") or ("x" if xtype == "date" or bucket != "none" else "value_desc")
    keys = list(totals)
    if sort == "x":
        keys.sort()
    elif sort == "value_asc":
        keys.sort(key=lambda k: totals[k])
    else:
        keys.sort(key=lambda k: -totals[k])
    other = None
    if len(keys) > limit:
        if sort == "x":
            keys = keys[-limit:]  # ช่วงเวลาล่าสุด
        else:
            rest = keys[limit - 1:] if ctype in ("pie", "doughnut") else []
            keys = keys[:limit - 1] if rest else keys[:limit]
            if rest and agg in ("sum", "count"):
                other = rest
    datasets = []
    for s in series:
        data = [_round(_agg(groups[s][k], agg)) if k in groups[s] else 0 for k in keys]
        if other is not None:
            data.append(_round(sum((_agg(groups[s][k], agg) or 0) for k in other if k in groups[s])))
        datasets.append({"label": (ycol or "จำนวน") if s == "_" else s, "data": data})
    labels = keys + (["อื่น ๆ"] if other is not None else [])
    return {"title": str(spec.get("title") or "")[:100] or f"{agg} ของ {ycol or 'แถว'} ตาม {xcol}", "type": ctype,
            "labels": labels, "datasets": datasets, "x_label": xcol, "y_label": f"{agg}({ycol})" if ycol else "จำนวน",
            "agg": agg, "stacked": bool(si is not None and ctype in ("bar", "horizontalBar", "area"))}


def group_table(tables: dict, types: dict, spec: dict) -> dict:
    t = tables.get(spec.get("table"))
    if t is None or spec.get("group_by") not in t.columns:
        raise ValueError("ตาราง/คอลัมน์ไม่ถูกต้อง")
    rows = _filter_rows(t, spec.get("filters"))
    gi = t.columns.index(spec["group_by"])
    ttypes = types.get(spec["table"], [])
    bucket = spec.get("bucket") or "none"
    vals = [v for v in (spec.get("values") or []) if isinstance(v, dict) and (v.get("column") in t.columns or v.get("agg") == "count")][:5]
    if not vals:
        vals = [{"agg": "count"}]
    groups = defaultdict(list)
    for r in rows:
        k = _x_key(r[gi], ttypes[gi] if gi < len(ttypes) else "text", bucket)
        if k is not None:
            groups[k].append(r)
    header = [spec["group_by"]] + [f"{v.get('agg', 'sum')}({v.get('column') or 'แถว'})" for v in vals]
    out = []
    for k, rs in groups.items():
        row = [k]
        for v in vals:
            if v.get("agg") == "count" and not v.get("column"):
                row.append(len(rs))
            else:
                ci = t.columns.index(v["column"])
                row.append(_round(_agg([r[ci] for r in rs if r[ci] is not None], v.get("agg", "sum"))))
        out.append(row)
    sort = spec.get("sort") or "value_desc"
    if sort == "x":
        out.sort(key=lambda r: r[0])
    else:
        out.sort(key=lambda r: (r[1] is None, -(r[1] or 0) if sort == "value_desc" else (r[1] or 0)))
    limit = max(1, min(int(spec.get("limit") or 20), 100))
    return {"title": str(spec.get("title") or "")[:100], "header": header, "rows": out[:limit], "total_groups": len(out)}


def auto_overview(tables: dict, types: dict) -> dict:
    """กราฟเริ่มต้นโดยไม่ต้องใช้ AI (ใช้เป็น fallback ถ้า AI วางแผนไม่สำเร็จ)"""
    charts, metrics = [], []
    for tid, t in tables.items():
        tt = types[tid]
        nums = [c for c, ty in zip(t.columns, tt) if ty == "number"]
        # เรียงคอลัมน์ตัวเลขจากผลรวมมากไปน้อย (มักเป็นยอดขาย/มูลค่า)
        sums = {c: sum(n for n in (to_number(r[t.columns.index(c)]) for r in t.rows[:5000]) if n is not None) for c in nums}
        nums.sort(key=lambda c: -abs(sums[c]))
        dates = [c for c, ty in zip(t.columns, tt) if ty == "date"]
        texts = [c for c, ty in zip(t.columns, tt) if ty == "text"]
        metrics.append({"label": f"จำนวนแถว ({t.name})", "table": tid, "agg": "count"})
        if nums:
            metrics.append({"label": f"รวม {nums[0]}", "table": tid, "column": nums[0], "agg": "sum"})
        if dates and nums:
            charts.append({"type": "line", "table": tid, "x": dates[0], "y": nums[0], "agg": "sum", "bucket": "month"})
        if texts and nums:
            charts.append({"type": "bar", "table": tid, "x": texts[0], "y": nums[0], "agg": "sum", "limit": 10})
        if len(charts) >= 3:
            break
    return {"charts": charts[:4], "metrics": metrics[:4], "tables": []}
