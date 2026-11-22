"""แยกข้อความ / ตาราง จากไฟล์เอกสาร — ใช้เฉพาะไลบรารี pure-Python (pypdf, openpyxl) + stdlib
รองรับ: PDF, XLSX/XLSM, CSV/TSV, DOCX, PPTX, TXT/MD/JSON/LOG, รูปภาพ (PNG/JPG/WEBP/GIF)
"""
import csv
import io
import json
import os
import re
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, time
from xml.etree import ElementTree as ET

MAX_ROWS = 200_000
MAX_TEXT_CHARS = 3_000_000

TEXT_EXT = {".txt", ".md", ".markdown", ".log", ".json", ".xml", ".html", ".htm", ".yaml", ".yml", ".ini", ".py", ".js", ".sql"}
IMAGE_EXT = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif"}
SUPPORTED_EXT = {".pdf", ".xlsx", ".xlsm", ".csv", ".tsv", ".docx", ".pptx", *TEXT_EXT, *IMAGE_EXT}
ACCEPT_ATTR = ",".join(sorted(SUPPORTED_EXT))


class UnsupportedFile(ValueError):
    pass


@dataclass
class Segment:
    text: str
    loc: str = ""  # เช่น "หน้า 3", "สไลด์ 2", "ชีต Sales แถว 1–40"


@dataclass
class Table:
    name: str
    columns: list
    rows: list  # list[list] ค่าดิบ (str/int/float/datetime/None)
    truncated: bool = False


@dataclass
class Document:
    kind: str  # "text" | "table" | "image"
    segments: list = field(default_factory=list)
    tables: list = field(default_factory=list)
    media_type: str = ""
    pages: int = 0
    warnings: list = field(default_factory=list)

    @property
    def text(self) -> str:
        out = []
        for s in self.segments:
            out.append((f"[{s.loc}]\n" if s.loc else "") + s.text)
        return "\n\n".join(out)


def ext_of(name: str) -> str:
    return os.path.splitext(name or "")[1].lower()


def check_supported(name: str):
    ext = ext_of(name)
    if ext in (".xls",):
        raise UnsupportedFile("ไฟล์ .xls (Excel รุ่นเก่า) ยังไม่รองรับ — กรุณาบันทึกเป็น .xlsx")
    if ext in (".doc", ".ppt"):
        raise UnsupportedFile(f"ไฟล์ {ext} (Office รุ่นเก่า) ยังไม่รองรับ — กรุณาบันทึกเป็น {ext}x")
    if ext not in SUPPORTED_EXT:
        raise UnsupportedFile(f"ไม่รองรับไฟล์ชนิด {ext or '(ไม่มีนามสกุล)'}")


def extract(path: str, name: str) -> Document:
    check_supported(name)
    ext = ext_of(name)
    if ext == ".pdf":
        return _pdf(path)
    if ext in (".xlsx", ".xlsm"):
        return _xlsx(path)
    if ext in (".csv", ".tsv"):
        return _csv(path, "\t" if ext == ".tsv" else None)
    if ext == ".docx":
        return _docx(path)
    if ext == ".pptx":
        return _pptx(path)
    if ext in IMAGE_EXT:
        return Document(kind="image", media_type=IMAGE_EXT[ext])
    return _text(path)


# ---------------------------------------------------------------------------
def _decode(raw: bytes) -> str:
    for enc in ("utf-8-sig", "utf-16") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else ("utf-8-sig", "cp874", "tis-620", "latin-1"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", "replace")


def _text(path: str) -> Document:
    with open(path, "rb") as fh:
        text = _decode(fh.read(MAX_TEXT_CHARS))
    return Document(kind="text", segments=[Segment(text)])


def _pdf(path: str) -> Document:
    from pypdf import PdfReader

    reader = PdfReader(path)
    doc = Document(kind="text", pages=len(reader.pages))
    empty = 0
    for i, page in enumerate(reader.pages, start=1):
        try:
            t = page.extract_text() or ""
        except Exception:  # noqa: BLE001 — หน้าเสียไม่ควรทำให้ทั้งไฟล์ล้ม
            t = ""
        t = re.sub(r"[ \t]+\n", "\n", t).strip()
        if not t:
            empty += 1
            continue
        doc.segments.append(Segment(t, f"หน้า {i}"))
    if doc.pages and empty == doc.pages:
        doc.warnings.append("PDF นี้ไม่มีข้อความให้อ่าน (น่าจะเป็นภาพสแกน) — ลองแปลงเป็นรูปภาพแล้วอัปโหลดแทน")
    elif empty:
        doc.warnings.append(f"มี {empty} หน้าที่ไม่มีข้อความ (อาจเป็นภาพ)")
    return doc


def _cell(v):
    if isinstance(v, (datetime, date)):
        return v if isinstance(v, datetime) else datetime(v.year, v.month, v.day)
    if isinstance(v, time):
        return v.isoformat()
    if isinstance(v, str):
        v = v.strip()
        return v or None
    return v


def _rows_to_table(name: str, rows_iter) -> Table | None:
    """หาแถวหัวตารางอัตโนมัติ (ข้ามแถวชื่อรายงาน/แถวว่างด้านบน)"""
    header, rows, truncated = None, [], False
    head_buf = []
    for raw in rows_iter:
        row = [_cell(v) for v in raw]
        while row and row[-1] is None:
            row.pop()
        if not any(v is not None for v in row):
            continue
        if header is None:
            head_buf.append(row)
            if len(head_buf) < 30:
                continue
            header, rows = _pick_header(head_buf)
            continue
        if len(rows) >= MAX_ROWS:
            truncated = True
            break
        rows.append(row)
    if header is None and head_buf:
        header, rows = _pick_header(head_buf)
    if header is None:
        return None
    width = max([len(header)] + [len(r) for r in rows[:2000]])
    cols, seen = [], {}
    for i in range(width):
        base = str(header[i]).strip() if i < len(header) and header[i] is not None else f"คอลัมน์ {i + 1}"
        if isinstance(header[i] if i < len(header) else None, datetime):
            base = header[i].strftime("%Y-%m-%d")
        n = seen.get(base, 0)
        seen[base] = n + 1
        cols.append(base if n == 0 else f"{base} ({n + 1})")
    rows = [r + [None] * (width - len(r)) if len(r) < width else r[:width] for r in rows]
    return Table(name=name, columns=cols, rows=rows, truncated=truncated)


def _pick_header(buf: list):
    filled = [sum(1 for v in r if v is not None) for r in buf]
    widest = max(filled)
    for i, (r, f) in enumerate(zip(buf, filled)):
        texty = sum(1 for v in r if isinstance(v, str))
        if f >= max(1, 0.6 * widest) and texty >= 0.5 * f:
            return r, buf[i + 1:]
    i = filled.index(widest)
    return buf[i], buf[i + 1:]


def _table_segments(t: Table, chunk_rows=40) -> list:
    segs = []
    for start in range(0, len(t.rows), chunk_rows):
        part = t.rows[start:start + chunk_rows]
        lines = []
        for r in part:
            cells = [f"{c}: {_fmt(v)}" for c, v in zip(t.columns, r) if v is not None]
            lines.append("; ".join(cells))
        segs.append(Segment("\n".join(lines), f"{t.name} แถว {start + 1}–{start + len(part)}"))
    return segs


def _fmt(v):
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d") if v.time() == time() else v.strftime("%Y-%m-%d %H:%M")
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def _xlsx(path: str) -> Document:
    import openpyxl

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    doc = Document(kind="table")
    for ws in wb.worksheets:
        t = _rows_to_table(f"ชีต {ws.title}", ws.iter_rows(values_only=True))
        if t and t.rows:
            doc.tables.append(t)
            if t.truncated:
                doc.warnings.append(f"{t.name} มีข้อมูลเกิน {MAX_ROWS:,} แถว — ใช้เฉพาะ {MAX_ROWS:,} แถวแรก")
    wb.close()
    if not doc.tables:
        doc.kind = "text"
        doc.warnings.append("ไม่พบตารางข้อมูลในไฟล์นี้")
    for t in doc.tables:
        doc.segments.extend(_table_segments(t))
    return doc


def _csv(path: str, delimiter=None) -> Document:
    with open(path, "rb") as fh:
        text = _decode(fh.read())
    if delimiter is None:
        try:
            delimiter = csv.Sniffer().sniff(text[:20000], delimiters=",;\t|").delimiter
        except csv.Error:
            delimiter = ","
    t = _rows_to_table("ตาราง", csv.reader(io.StringIO(text), delimiter=delimiter))
    doc = Document(kind="table" if t and t.rows else "text")
    if t and t.rows:
        doc.tables.append(t)
        doc.segments = _table_segments(t)
        if t.truncated:
            doc.warnings.append(f"ข้อมูลเกิน {MAX_ROWS:,} แถว — ใช้เฉพาะ {MAX_ROWS:,} แถวแรก")
    else:
        doc.segments = [Segment(text[:MAX_TEXT_CHARS])]
    return doc


# --- Office Open XML (อ่านตรงจาก zip ไม่ต้องใช้ python-docx / python-pptx) ---
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"


def _docx(path: str) -> Document:
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read("word/document.xml"))
    body = root.find(f"{W}body")
    blocks, buf = [], []

    def para_text(p):
        return "".join(t.text or "" for t in p.iter(f"{W}t")).strip()

    for el in list(body) if body is not None else []:
        if el.tag == f"{W}p":
            t = para_text(el)
            style = el.find(f"{W}pPr/{W}pStyle")
            if t and style is not None and "heading" in (style.get(f"{W}val") or "").lower():
                t = "## " + t
            if t:
                buf.append(t)
        elif el.tag == f"{W}tbl":
            rows = []
            for tr in el.iter(f"{W}tr"):
                cells = [" ".join(para_text(p) for p in tc.iter(f"{W}p")).strip() for tc in tr.iter(f"{W}tc")]
                rows.append(" | ".join(cells))
            if rows:
                buf.append("[ตาราง]\n" + "\n".join(rows))
    # แบ่งเป็นช่วง ๆ ละ ~4000 ตัวอักษรเพื่อให้อ้างอิงตำแหน่งได้
    part, size, n = [], 0, 1
    for b in buf:
        part.append(b)
        size += len(b)
        if size > 4000:
            blocks.append(Segment("\n\n".join(part), f"ส่วนที่ {n}"))
            part, size, n = [], 0, n + 1
    if part:
        blocks.append(Segment("\n\n".join(part), f"ส่วนที่ {n}" if blocks else ""))
    doc = Document(kind="text", segments=blocks)
    if not blocks:
        doc.warnings.append("ไม่พบข้อความในเอกสาร Word นี้")
    return doc


def _pptx(path: str) -> Document:
    doc = Document(kind="text")
    with zipfile.ZipFile(path) as z:
        names = [n for n in z.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n)]
        names.sort(key=lambda n: int(re.search(r"(\d+)\.xml$", n).group(1)))
        for i, n in enumerate(names, start=1):
            root = ET.fromstring(z.read(n))
            paras = []
            for p in root.iter(f"{A}p"):
                t = "".join(r.text or "" for r in p.iter(f"{A}t")).strip()
                if t:
                    paras.append(t)
            note_name = f"ppt/notesSlides/notesSlide{re.search(r'(\d+)', n.rsplit('/', 1)[1]).group(1)}.xml"
            if note_name in z.namelist():
                nroot = ET.fromstring(z.read(note_name))
                notes = [t.text for t in nroot.iter(f"{A}t") if t.text and t.text.strip() and not t.text.strip().isdigit()]
                if notes:
                    paras.append("หมายเหตุผู้บรรยาย: " + " ".join(notes))
            if paras:
                doc.segments.append(Segment("\n".join(paras), f"สไลด์ {i}"))
        doc.pages = len(names)
    if not doc.segments:
        doc.warnings.append("ไม่พบข้อความในสไลด์")
    return doc


# ---------------------------------------------------------------------------
# cache ตารางเป็น JSON (โหลดเร็วกว่าการ parse Excel ซ้ำ)
def _json_default(o):
    if isinstance(o, datetime):
        return {"__dt__": o.isoformat()}
    return str(o)


def _json_hook(d):
    if "__dt__" in d:
        return datetime.fromisoformat(d["__dt__"])
    return d


def save_tables(tables: list, path: str):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump([{"name": t.name, "columns": t.columns, "rows": t.rows, "truncated": t.truncated} for t in tables],
                  fh, ensure_ascii=False, default=_json_default)


def load_tables(path: str) -> list:
    with open(path, encoding="utf-8") as fh:
        return [Table(**t) for t in json.load(fh, object_hook=_json_hook)]
