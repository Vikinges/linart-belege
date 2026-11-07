"""LinArt Belege - local receipts & invoices -> EÜR (Kleinunternehmer § 19 UStG).

Everything stays on this machine: originals in an archive (unchanged, SHA-256),
extraction by a local vision model in LM Studio, data in SQLite.
Not tax advice - a pre-sorting tool for the EÜR / the tax advisor.
Run: start_belege.bat  ->  http://127.0.0.1:7880
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import shutil
import sqlite3
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Any, Optional

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get("BELEGE_DATA", ROOT / "data"))
ARCHIVE = DATA / "archiv"
PREVIEW = DATA / "preview"
INBOX = Path(os.environ.get("BELEGE_EINGANG", ROOT / "Eingang"))
for d in (ARCHIVE, PREVIEW, INBOX):
    d.mkdir(parents=True, exist_ok=True)
DB = DATA / "belege.db"
ALLOWED = {".pdf", ".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".tif", ".tiff"}

import extract as ex  # noqa: E402

# ---------------------------------------------------------------------------
# DB
# ---------------------------------------------------------------------------
COLS = ["doc_type", "date", "vendor", "invoice_number", "total_gross", "currency", "net_total", "vat_total",
        "vat_lines", "payment_method", "description", "category", "confidence", "warnings", "notes"]
_dblock = threading.Lock()


def db() -> sqlite3.Connection:
    c = sqlite3.connect(DB, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c


with db() as c:
    c.execute("""CREATE TABLE IF NOT EXISTS belege(
        id INTEGER PRIMARY KEY AUTOINCREMENT, created TEXT, status TEXT, file_name TEXT, archive_path TEXT,
        sha256 TEXT UNIQUE, doc_type TEXT, date TEXT, vendor TEXT, invoice_number TEXT, total_gross REAL,
        currency TEXT, net_total REAL, vat_total REAL, vat_lines TEXT, payment_method TEXT, description TEXT,
        category TEXT, confidence REAL, warnings TEXT, notes TEXT, error TEXT, confirmed TEXT)""")


def row(r: sqlite3.Row) -> dict:
    d = dict(r)
    for k in ("vat_lines", "warnings"):
        try:
            d[k] = json.loads(d[k]) if d[k] else []
        except Exception:
            d[k] = []
    d["preview_url"] = f"/files/preview/{d['id']}.jpg"
    d["original_url"] = f"/api/belege/{d['id']}/original"
    d["category_label"] = ex.CATEGORIES.get(d.get("category") or "", ("", ""))[0]
    return d


# ---------------------------------------------------------------------------
# import + extraction queue
# ---------------------------------------------------------------------------
QUEUE: list[int] = []
QCOND = threading.Condition()
STATE = {"current": None, "last_error": None}


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def import_file(src: Path, orig_name: str) -> dict:
    suf = Path(orig_name).suffix.lower()
    if suf not in ALLOWED:
        return {"file": orig_name, "status": "abgelehnt", "reason": f"Format {suf} nicht unterstützt"}
    sha = sha256_file(src)
    with _dblock, db() as c:
        dup = c.execute("SELECT id FROM belege WHERE sha256=?", (sha,)).fetchone()
        if dup:
            return {"file": orig_name, "status": "duplikat", "id": dup["id"]}
        tgt_dir = ARCHIVE / "_neu"
        tgt_dir.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r"[^\w.\-]+", "_", orig_name)[-80:]
        tgt = tgt_dir / f"{sha[:10]}_{safe}"
        shutil.copy2(src, tgt)
        cur = c.execute("INSERT INTO belege(created,status,file_name,archive_path,sha256) VALUES(?,?,?,?,?)",
                        (time.strftime("%Y-%m-%d %H:%M:%S"), "neu", orig_name, str(tgt), sha))
        bid = cur.lastrowid
    try:
        ex.preview_image(tgt, PREVIEW / f"{bid}.jpg")
    except Exception as e:
        print(f"[preview] {bid}: {e}")
    enqueue(bid)
    return {"file": orig_name, "status": "importiert", "id": bid}


def enqueue(bid: int) -> None:
    with QCOND:
        if bid not in QUEUE:
            QUEUE.append(bid)
        QCOND.notify()


def set_fields(bid: int, fields: dict) -> None:
    if not fields:
        return
    keys = list(fields)
    vals = [json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v for v in fields.values()]
    with _dblock, db() as c:
        c.execute(f"UPDATE belege SET {', '.join(k + '=?' for k in keys)} WHERE id=?", (*vals, bid))


def worker() -> None:
    while True:
        with QCOND:
            while not QUEUE:
                QCOND.wait()
            bid = QUEUE[0]
        STATE["current"] = bid
        try:
            with db() as c:
                r = c.execute("SELECT * FROM belege WHERE id=?", (bid,)).fetchone()
            if r and r["status"] != "geprueft":
                set_fields(bid, {"status": "verarbeitung", "error": None})
                d = ex.extract(Path(r["archive_path"]))
                fields = {k: d.get(k) for k in COLS if k in d}
                fields["status"] = "zu_pruefen"
                set_fields(bid, fields)
                STATE["last_error"] = None
        except Exception as e:
            msg = f"{type(e).__name__}: {e}"
            if "Connection refused" in msg or "URLError" in msg or "10061" in msg:
                msg = "LM Studio nicht erreichbar – LM Studio starten (Server an, Port 1234)."
            STATE["last_error"] = msg
            print(traceback.format_exc())
            set_fields(bid, {"status": "fehler", "error": msg})
        finally:
            STATE["current"] = None
            with QCOND:
                if QUEUE and QUEUE[0] == bid:
                    QUEUE.pop(0)


def inbox_watcher() -> None:
    """Files dropped into the 'Eingang' folder are imported and moved to Eingang/_importiert."""
    done = INBOX / "_importiert"
    done.mkdir(exist_ok=True)
    while True:
        try:
            for p in INBOX.iterdir():
                if p.is_file() and p.suffix.lower() in ALLOWED:
                    s1 = p.stat().st_size
                    time.sleep(1.0)
                    if p.stat().st_size != s1:
                        continue      # still being written / synced
                    import_file(p, p.name)
                    shutil.move(str(p), str(done / f"{int(time.time())}_{p.name}"))
        except Exception as e:
            print(f"[eingang] {e}")
        time.sleep(5)


def requeue_unfinished() -> None:
    with db() as c:
        for r in c.execute("SELECT id FROM belege WHERE status IN ('neu','verarbeitung')"):
            enqueue(r["id"])


threading.Thread(target=worker, daemon=True).start()
threading.Thread(target=inbox_watcher, daemon=True).start()
requeue_unfinished()

# ---------------------------------------------------------------------------
# summary / EÜR
# ---------------------------------------------------------------------------
def deductible(r: dict) -> float:
    amt = float(r.get("total_gross") or 0)
    cat = r.get("category")
    if cat == "bewirtung":
        return round(amt * 0.7, 2)
    if cat in ("privat", "afa", "einnahme"):
        return 0.0
    return amt


def summary(year: Optional[int], only_confirmed: bool) -> dict:
    with db() as c:
        rows = [row(r) for r in c.execute("SELECT * FROM belege ORDER BY date")]
    if year:
        rows = [r for r in rows if (r.get("date") or "").startswith(str(year))]
    if only_confirmed:
        rows = [r for r in rows if r["status"] == "geprueft"]
    cats: dict[str, dict] = {}
    months: dict[str, dict] = {}
    inc = exp = 0.0
    afa_items = []
    for r in rows:
        cat = r.get("category") or "sonstige"
        amt = float(r.get("total_gross") or 0)
        c = cats.setdefault(cat, {"key": cat, "label": ex.CATEGORIES.get(cat, (cat,))[0], "count": 0, "brutto": 0.0, "abziehbar": 0.0})
        c["count"] += 1
        c["brutto"] = round(c["brutto"] + amt, 2)
        m = months.setdefault((r.get("date") or "????-??")[:7], {"einnahmen": 0.0, "ausgaben": 0.0})
        if r.get("doc_type") == "einnahme" or cat == "einnahme":
            inc += amt
            m["einnahmen"] = round(m["einnahmen"] + amt, 2)
        else:
            dd = deductible(r)
            c["abziehbar"] = round(c["abziehbar"] + dd, 2)
            exp += dd
            m["ausgaben"] = round(m["ausgaben"] + dd, 2)
            if cat == "afa":
                afa_items.append({"id": r["id"], "date": r["date"], "vendor": r["vendor"], "brutto": amt})
    return {"year": year, "only_confirmed": only_confirmed, "count": len(rows),
            "einnahmen": round(inc, 2), "ausgaben_abziehbar": round(exp, 2), "gewinn": round(inc - exp, 2),
            "kategorien": sorted(cats.values(), key=lambda x: -x["brutto"]),
            "monate": dict(sorted(months.items())), "afa_items": afa_items,
            "hinweis": "Kleinunternehmer § 19 UStG: Ausgaben brutto (keine Vorsteuer). Bewirtung 70 %. "
                       "Anlagegüter > 800 € netto über AfA verteilen. Orientierung, keine Steuerberatung."}


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
from fastapi import Body, FastAPI, File, HTTPException, UploadFile  # noqa: E402
from fastapi.responses import FileResponse, HTMLResponse, Response  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

app = FastAPI(title="LinArt Belege")
app.mount("/files/preview", StaticFiles(directory=str(PREVIEW)), name="preview")


@app.get("/", response_class=HTMLResponse)
def index():
    return (ROOT / "static" / "index.html").read_text(encoding="utf-8")


@app.get("/api/status")
def status():
    ok, loaded = False, []
    try:
        import urllib.request
        with urllib.request.urlopen(ex.LMSTUDIO + "/models", timeout=2) as r:
            ok = True
            loaded = [m["id"] for m in json.loads(r.read())["data"]]
    except Exception:
        pass
    return {"llm_ok": ok, "model": ex.MODEL, "model_available": ex.MODEL in loaded,
            "queue": len(QUEUE), "current": STATE["current"], "last_error": STATE["last_error"],
            "eingang": str(INBOX), "categories": {k: v[0] for k, v in ex.CATEGORIES.items()}}


@app.post("/api/upload")
async def upload(files: list[UploadFile] = File(...)):
    out = []
    tmp = DATA / "_tmp"
    tmp.mkdir(exist_ok=True)
    for f in files:
        p = tmp / f"{time.time_ns()}{Path(f.filename or 'x').suffix}"
        with open(p, "wb") as fh:
            shutil.copyfileobj(f.file, fh)
        try:
            out.append(import_file(p, f.filename or p.name))
        finally:
            p.unlink(missing_ok=True)
    return out


@app.get("/api/belege")
def list_belege(year: Optional[int] = None, status: Optional[str] = None):
    with db() as c:
        rows = [row(r) for r in c.execute("SELECT * FROM belege ORDER BY COALESCE(date, created) DESC, id DESC")]
    if year:
        rows = [r for r in rows if (r.get("date") or r["created"]).startswith(str(year))]
    if status:
        rows = [r for r in rows if r["status"] == status]
    return rows


@app.get("/api/belege/{bid}")
def get_beleg(bid: int):
    with db() as c:
        r = c.execute("SELECT * FROM belege WHERE id=?", (bid,)).fetchone()
    if not r:
        raise HTTPException(404, "nicht gefunden")
    return row(r)


@app.put("/api/belege/{bid}")
def update_beleg(bid: int, body: dict = Body(...)):
    cur = get_beleg(bid)
    fields = {k: body[k] for k in COLS if k in body and k != "warnings"}
    if "total_gross" in fields or "vat_lines" in fields or "category" in fields:
        merged = {**cur, **fields}
        merged = ex.postprocess(merged)
        fields["warnings"] = merged["warnings"]
        fields["net_total"], fields["vat_total"] = merged["net_total"], merged["vat_total"]
    if body.get("confirm"):
        d = fields.get("date", cur.get("date")) or ""
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", d):
            raise HTTPException(400, "Datum fehlt oder ungültig (YYYY-MM-DD)")
        fields["status"] = "geprueft"
        fields["confirmed"] = time.strftime("%Y-%m-%d %H:%M:%S")
        # move original into the year folder with a readable name (bytes unchanged, SHA-256 kept)
        src = Path(cur["archive_path"])
        vendor = re.sub(r"[^\w\-]+", "_", (fields.get("vendor", cur.get("vendor")) or "beleg"))[:40]
        amt = f"{float(fields.get('total_gross', cur.get('total_gross')) or 0):.2f}".replace(".", ",")
        dst = ARCHIVE / d[:4] / f"{d}_{vendor}_{amt}EUR_{cur['sha256'][:8]}{src.suffix.lower()}"
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.exists() and src != dst:
            shutil.move(str(src), str(dst))
            fields["archive_path"] = str(dst)
    elif body.get("unconfirm"):
        fields["status"] = "zu_pruefen"
        fields["confirmed"] = None
    set_fields(bid, fields)
    return get_beleg(bid)


@app.post("/api/belege/{bid}/reextract")
def reextract(bid: int):
    cur = get_beleg(bid)
    if cur["status"] == "geprueft":
        raise HTTPException(400, "Geprüfte Belege zuerst entsperren")
    set_fields(bid, {"status": "neu"})
    enqueue(bid)
    return {"ok": True}


@app.delete("/api/belege/{bid}")
def delete_beleg(bid: int):
    cur = get_beleg(bid)
    if cur["status"] == "geprueft":
        raise HTTPException(400, "Geprüfte Belege können nicht gelöscht werden (GoBD). Erst entsperren.")
    Path(cur["archive_path"]).unlink(missing_ok=True)
    (PREVIEW / f"{bid}.jpg").unlink(missing_ok=True)
    with _dblock, db() as c:
        c.execute("DELETE FROM belege WHERE id=?", (bid,))
    return {"ok": True}


@app.get("/api/belege/{bid}/original")
def original(bid: int):
    cur = get_beleg(bid)
    p = Path(cur["archive_path"])
    if not p.exists():
        raise HTTPException(404, "Original fehlt")
    return FileResponse(p, filename=cur["file_name"])


@app.get("/api/summary")
def api_summary(year: Optional[int] = None, only_confirmed: bool = True):
    return summary(year, only_confirmed)


def _rows_for_export(year: Optional[int], only_confirmed: bool) -> list[dict]:
    rows = list_belege(year)
    if only_confirmed:
        rows = [r for r in rows if r["status"] == "geprueft"]
    return sorted(rows, key=lambda r: r.get("date") or "")


EXPORT_COLS = [("date", "Datum"), ("doc_type", "Art"), ("vendor", "Partner"), ("invoice_number", "Beleg-Nr."),
               ("description", "Beschreibung"), ("category_label", "Kategorie (EÜR)"), ("total_gross", "Brutto EUR"),
               ("net_total", "Netto EUR"), ("vat_total", "USt EUR (nicht abziehbar)"), ("abziehbar", "Abziehbar EUR"),
               ("payment_method", "Zahlung"), ("status", "Status"), ("file_name", "Originaldatei"),
               ("archive_path", "Archivpfad"), ("sha256", "SHA-256")]


@app.get("/api/export.csv")
def export_csv(year: Optional[int] = None, only_confirmed: bool = True):
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow([h for _, h in EXPORT_COLS])
    for r in _rows_for_export(year, only_confirmed):
        r["abziehbar"] = deductible(r) if r.get("doc_type") != "einnahme" else ""
        w.writerow([str(r.get(k, "") if r.get(k) is not None else "").replace(".", ",") if k in ("total_gross", "net_total", "vat_total", "abziehbar") else r.get(k, "") for k, _ in EXPORT_COLS])
    return Response("﻿" + buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="Belege_{year or "alle"}.csv"'})


@app.get("/api/export.xlsx")
def export_xlsx(year: Optional[int] = None, only_confirmed: bool = True):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    wb = Workbook()
    ws = wb.active
    ws.title = "Belege"
    ws.append([h for _, h in EXPORT_COLS])
    for r in _rows_for_export(year, only_confirmed):
        r["abziehbar"] = deductible(r) if r.get("doc_type") != "einnahme" else None
        ws.append([r.get(k) for k, _ in EXPORT_COLS])
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="1C2129")
    for col in ("G", "H", "I", "J"):
        for cell in ws[col][1:]:
            cell.number_format = '#,##0.00 "€"'
    widths = [11, 9, 26, 14, 40, 38, 11, 11, 13, 12, 12, 11, 28, 50, 20]
    for i, wdt in enumerate(widths):
        ws.column_dimensions[chr(65 + i)].width = wdt
    ws.freeze_panes = "A2"
    s = summary(year, only_confirmed)
    ws2 = wb.create_sheet("EÜR Übersicht")
    ws2.append([f"EÜR-Vorbereitung {year or 'alle Jahre'} – LinArt Labs (Kleinunternehmer § 19 UStG)"])
    ws2["A1"].font = Font(bold=True, size=13)
    ws2.append([s["hinweis"]])
    ws2.append([])
    ws2.append(["Kategorie", "Anzahl", "Brutto EUR", "Abziehbar EUR"])
    for c in ws2[4]:
        c.font = Font(bold=True)
    for k in s["kategorien"]:
        ws2.append([k["label"], k["count"], k["brutto"], k["abziehbar"]])
    ws2.append([])
    ws2.append(["Betriebseinnahmen", None, s["einnahmen"]])
    ws2.append(["Betriebsausgaben (abziehbar, ohne AfA)", None, s["ausgaben_abziehbar"]])
    ws2.append(["Ergebnis vor AfA", None, s["gewinn"]])
    for r in ws2.iter_rows(min_row=5, min_col=3, max_col=4):
        for cell in r:
            cell.number_format = '#,##0.00 "€"'
    ws2.column_dimensions["A"].width = 52
    ws2.column_dimensions["C"].width = 14
    ws2.column_dimensions["D"].width = 14
    if s["afa_items"]:
        ws3 = wb.create_sheet("Anlagegüter (AfA)")
        ws3.append(["Datum", "Partner", "Brutto EUR", "Hinweis"])
        for a in s["afa_items"]:
            ws3.append([a["date"], a["vendor"], a["brutto"], "Nutzungsdauer festlegen, AfA verteilen"])
    buf = io.BytesIO()
    wb.save(buf)
    return Response(buf.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="EUER_Belege_{year or "alle"}.xlsx"'})


if __name__ == "__main__":
    import uvicorn
    import webbrowser
    port = int(os.environ.get("BELEGE_PORT", "7880"))
    if os.environ.get("BELEGE_NO_BROWSER") != "1":
        threading.Timer(2.0, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
