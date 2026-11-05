"""Local data: the TN VED / ETT tariff table (SQLite + FTS5) and bundled reference JSON."""

from __future__ import annotations

import csv
import json
import os
import re
import sqlite3
from datetime import date, datetime, timezone
from importlib import resources
from pathlib import Path


def data_dir() -> Path:
    d = os.environ.get("XONTA_CUSTOMS_DATA")
    p = Path(d) if d else Path.home() / ".xonta-customs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def db_path() -> Path:
    return data_dir() / "tariff.sqlite"


def normalize_code(code: str) -> str:
    return re.sub(r"\D", "", str(code or ""))


def format_code(code: str) -> str:
    c = normalize_code(code)
    if len(c) == 10:
        return f"{c[:4]} {c[4:6]} {c[6:9]} {c[9]}"
    return c


# ---------------------------------------------------------------- bundled JSON

def _bundled(name: str) -> dict:
    override = data_dir() / name
    if override.exists():
        return json.loads(override.read_text(encoding="utf-8"))
    return json.loads(resources.files("xonta_customs").joinpath("data", name).read_text(encoding="utf-8"))


def antidumping_data() -> dict:
    return _bundled("antidumping.json")


def rulings_data() -> dict:
    return _bundled("rulings.json")


def _stem_match(text: str, keywords: list[str]) -> bool:
    t = text.lower()
    for kw in keywords:
        parts = kw.lower().split()
        if all(p in t for p in parts):
            return True
    return False


def find_measures(code: str | None, origin: str | None, query: str | None, today: date | None = None) -> list[dict]:
    today = today or date.today()
    data = antidumping_data()
    code_n = normalize_code(code) if code else ""
    origin_u = (origin or "").strip().upper() or None
    out = []
    for m in data["measures"]:
        by_code = bool(code_n) and any(code_n.startswith(p) for p in m["tnved_prefixes"])
        by_text = bool(query) and _stem_match(query, m["keywords"])
        if not (by_code or by_text):
            continue
        if origin_u and origin_u not in m["origin"]:
            continue
        item = dict(m)
        vu = m.get("valid_until")
        item["active"] = True if vu is None else date.fromisoformat(vu) >= today
        item["matched_by"] = "code" if by_code else "keywords"
        out.append(item)
    return out


def find_rulings(query: str | None, code: str | None) -> list[dict]:
    data = rulings_data()
    code_n = normalize_code(code) if code else ""
    words = [w for w in re.split(r"\W+", (query or "").lower()) if len(w) >= 3]
    out = []
    for r in data["rulings"]:
        hit = False
        if code_n and (r["tnved"].startswith(code_n[: len(r["tnved"])]) or code_n.startswith(r["tnved"])):
            hit = True
        if words:
            prod = r["product"].lower()
            # crude stemming: compare first 5 letters of each word
            if any(w[:5] in prod for w in words):
                hit = True
        if hit:
            out.append(r)
    return out


# ---------------------------------------------------------------- tariff DB

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS tnved (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    duty_raw TEXT,
    unit TEXT
);
CREATE VIRTUAL TABLE IF NOT EXISTS tnved_fts USING fts5(code, name, tokenize='unicode61 remove_diacritics 2');
"""


def connect(path: Path | None = None) -> sqlite3.Connection:
    con = sqlite3.connect(str(path or db_path()))
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


_HEADER_HINTS = {
    "code": ("код",),
    "name": ("наимен", "описан", "name"),
    "duty": ("пошлин", "ставк", "ett", "етт", "duty"),
    "unit": ("доп", "ед. изм", "единиц", "unit"),
}


def _detect_columns(header: list[str]) -> dict[str, int]:
    cols: dict[str, int] = {}
    for i, h in enumerate(header):
        hl = str(h or "").strip().lower()
        for key, hints in _HEADER_HINTS.items():
            if key in cols:
                continue
            if any(x in hl for x in hints):
                # "код" also appears in "доп. ед. изм. (код)"; prefer the first plain match
                if key == "code" and ("ед" in hl or "стран" in hl):
                    continue
                cols[key] = i
                break
    if "code" not in cols or "name" not in cols:
        raise ValueError(f"Не нашёл колонки кода и наименования в заголовке: {header}")
    return cols


def _iter_rows(path: Path):
    suffix = path.suffix.lower()
    if suffix in (".xlsx", ".xlsm"):
        from openpyxl import load_workbook

        wb = load_workbook(path, read_only=True, data_only=True)
        ws = wb.active
        for row in ws.iter_rows(values_only=True):
            yield [("" if v is None else v) for v in row]
    elif suffix in (".csv", ".tsv", ".txt"):
        raw = path.read_bytes()
        for enc in ("utf-8-sig", "cp1251"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        first = next((ln for ln in text.splitlines() if ln.strip()), "")
        delim = max(";\t,", key=first.count)
        yield from csv.reader(text.splitlines(), delimiter=delim)
    else:
        raise ValueError("Поддерживаются .xlsx и .csv")


def load_tariff(path: Path, source: str, db: Path | None = None) -> int:
    rows = _iter_rows(path)
    cols = None
    for row in rows:
        try:
            cols = _detect_columns([str(x) for x in row])
            break
        except ValueError:
            continue
    if cols is None:
        raise ValueError("В файле не найден заголовок с колонками «Код» и «Наименование»")

    con = connect(db)
    with con:
        con.execute("DELETE FROM tnved")
        con.execute("DELETE FROM tnved_fts")
        n = 0
        for row in rows:
            if len(row) <= max(cols.values()):
                row = list(row) + [""] * (max(cols.values()) + 1 - len(row))
            code = normalize_code(str(row[cols["code"]]))
            name = str(row[cols["name"]]).strip()
            if not code or not name or len(code) > 10:
                continue
            duty = str(row[cols["duty"]]).strip() if "duty" in cols else ""
            unit = str(row[cols["unit"]]).strip() if "unit" in cols else ""
            con.execute(
                "INSERT OR REPLACE INTO tnved(code, name, duty_raw, unit) VALUES (?,?,?,?)",
                (code, name, duty or None, unit or None),
            )
            n += 1
        con.execute("INSERT INTO tnved_fts(code, name) SELECT code, name FROM tnved")
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        con.execute("INSERT OR REPLACE INTO meta VALUES ('loaded_at', ?)", (now,))
        con.execute("INSERT OR REPLACE INTO meta VALUES ('source', ?)", (source,))
        con.execute("INSERT OR REPLACE INTO meta VALUES ('rows', ?)", (str(n),))
    con.close()
    return n


def tariff_meta(db: Path | None = None) -> dict:
    p = db or db_path()
    if not p.exists():
        return {"loaded": False}
    con = connect(p)
    meta = {r["key"]: r["value"] for r in con.execute("SELECT key, value FROM meta")}
    con.close()
    meta["loaded"] = int(meta.get("rows", 0) or 0) > 0
    return meta


_STOP = {"из", "для", "и", "в", "на", "с", "со", "по", "от", "до", "или", "без", "не", "а", "of", "the", "and", "for"}
_ENDINGS = sorted(
    "иями ями ами ого его ому ему ыми ими ией ей ой ий ый ая яя ое ее ые ие ов ев ам ям ах ях ом ем ую юю "
    "ных ных ный ной ная ное ные ную ним ним а я о е ы и у ю ь й".split(),
    key=len,
    reverse=True,
)


def _stem(word: str) -> str:
    w = word.replace("ё", "е")
    if not re.search(r"[а-я]", w):
        return w
    for end in _ENDINGS:
        if w.endswith(end) and len(w) - len(end) >= 3:
            return w[: -len(end)]
    return w


def _fts_query(text: str) -> str:
    words = [w for w in re.split(r"[^\w]+", text.lower()) if len(w) >= 2 and w not in _STOP]
    terms = []
    for w in words:
        terms.append(f'"{_stem(w)}"*')
    return " OR ".join(dict.fromkeys(terms))


def search(query: str, limit: int = 10, db: Path | None = None) -> list[dict]:
    con = connect(db)
    q = query.strip()
    code_n = normalize_code(q)
    if code_n and len(code_n) >= 2 and len(code_n) == len(re.sub(r"\s", "", q)):
        rows = con.execute(
            "SELECT code, name, duty_raw, unit FROM tnved WHERE code LIKE ? ORDER BY code LIMIT ?",
            (code_n + "%", limit),
        ).fetchall()
    else:
        fq = _fts_query(q)
        if not fq:
            return []
        rows = con.execute(
            "SELECT t.code, t.name, t.duty_raw, t.unit FROM tnved_fts f JOIN tnved t ON t.code = f.code "
            "WHERE tnved_fts MATCH ? ORDER BY bm25(tnved_fts), length(t.code) DESC LIMIT ?",
            (fq, limit),
        ).fetchall()
    con.close()
    return [dict(r) | {"code_formatted": format_code(r["code"])} for r in rows]


def get_code(code: str, db: Path | None = None) -> dict | None:
    con = connect(db)
    c = normalize_code(code)
    row = con.execute("SELECT code, name, duty_raw, unit FROM tnved WHERE code = ?", (c,)).fetchone()
    parents = []
    if row:
        for n in (2, 4, 6, 8, 9):
            if n < len(c):
                p = con.execute("SELECT code, name FROM tnved WHERE code = ?", (c[:n],)).fetchone()
                if p:
                    parents.append(dict(p))
    con.close()
    if not row:
        return None
    return dict(row) | {"code_formatted": format_code(row["code"]), "parents": parents}
