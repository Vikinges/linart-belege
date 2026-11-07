"""Receipt / invoice extraction with a local vision LLM (LM Studio, OpenAI-compatible API).

Nothing leaves the machine: the model runs in LM Studio on localhost.
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
import urllib.request
from pathlib import Path
from typing import Optional

from PIL import Image, ImageOps

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except Exception:
    pass

LMSTUDIO = os.environ.get("BELEGE_LLM_URL", "http://127.0.0.1:1234/v1")
MODEL = os.environ.get("BELEGE_LLM_MODEL", "qwen/qwen3-vl-30b")
# Describe YOUR business so the model can tell income from expenses and pick categories.
BUSINESS_NAME = os.environ.get("BELEGE_BUSINESS_NAME", "Muster GmbH")
BUSINESS_DESC = os.environ.get("BELEGE_BUSINESS_DESC", "baut Elektronik und Software und erbringt IT-Dienstleistungen")

# Categories oriented on Anlage EÜR. Key -> (German label, kind)
CATEGORIES = {
    "einnahme": ("Betriebseinnahmen (Kleinunternehmer, § 19 UStG)", "in"),
    "waren": ("Waren, Roh- und Hilfsstoffe (Material, Bauteile)", "out"),
    "fremdleistung": ("Bezogene Fremdleistungen", "out"),
    "gwg": ("Geringwertige Wirtschaftsgüter (GWG, netto 250–800 €)", "out"),
    "afa": ("Anlagegut – Abschreibung (AfA, netto > 800 €)", "out"),
    "werkzeug": ("Werkzeug / Kleingeräte (netto ≤ 250 €)", "out"),
    "software": ("Software, IT-Dienste, Server, Domains", "out"),
    "telekom": ("Telekommunikation (Telefon, Internet)", "out"),
    "porto": ("Porto, Versand", "out"),
    "buero": ("Büromaterial", "out"),
    "werbung": ("Werbekosten", "out"),
    "fortbildung": ("Fortbildung, Fachliteratur", "out"),
    "beratung": ("Rechts- und Steuerberatung, Buchführung", "out"),
    "miete": ("Miete, Raumkosten", "out"),
    "kfz": ("Kfz-Kosten (Kraftstoff, Wartung)", "out"),
    "reise": ("Reisekosten (Fahrt, Übernachtung)", "out"),
    "bewirtung": ("Bewirtung (70 % abziehbar)", "out"),
    "versicherung": ("Versicherungen, Beiträge", "out"),
    "bank": ("Bank- und Kontogebühren", "out"),
    "sonstige": ("Sonstige Betriebsausgaben", "out"),
    "privat": ("Privat – nicht betrieblich", "none"),
}

SCHEMA = {
    "type": "object",
    "properties": {
        "doc_type": {"type": "string", "enum": ["ausgabe", "einnahme", "unklar"]},
        "date": {"type": "string", "description": "Belegdatum YYYY-MM-DD"},
        "vendor": {"type": "string"},
        "invoice_number": {"type": "string"},
        "total_gross": {"type": "number"},
        "currency": {"type": "string"},
        "vat_lines": {"type": "array", "items": {"type": "object", "properties": {
            "rate": {"type": "number"}, "net": {"type": "number"}, "vat": {"type": "number"}},
            "required": ["rate", "net", "vat"]}},
        "payment_method": {"type": "string"},
        "description": {"type": "string", "description": "kurze Beschreibung auf Deutsch, was gekauft/verkauft wurde"},
        "category": {"type": "string", "enum": list(CATEGORIES.keys())},
        "confidence": {"type": "number"},
        "notes": {"type": "string"},
    },
    "required": ["doc_type", "date", "vendor", "total_gross", "currency", "vat_lines",
                 "description", "category", "confidence"],
}

SYSTEM = (
    "Du bist ein sorgfältiger Buchhaltungsassistent für ein deutsches Kleingewerbe "
    "(Kleinunternehmer nach § 19 UStG, Gewinnermittlung per EÜR nach § 4 Abs. 3 EStG). "
    f"Das Unternehmen '{BUSINESS_NAME}' {BUSINESS_DESC}. Lies den Beleg exakt ab. Erfinde nichts: unlesbare Felder leer lassen "
    "und confidence senken. Beträge als Zahl mit Punkt. Datum als YYYY-MM-DD. "
    f"doc_type='einnahme' nur wenn {BUSINESS_NAME} der Rechnungssteller ist, sonst 'ausgabe'. "
    "vendor = der Geschäftspartner (bei Einnahmen der Kunde). invoice_number = Rechnungs-/Beleg-/Bon-Nr. immer "
    "übernehmen, wenn sichtbar. payment_method = Bar, Karte, Überweisung, PayPal usw., wenn erkennbar. "
    "Kategorie nach Inhalt wählen; Elektronikbauteile/Material = 'waren'; einzelne Geräte/Werkzeuge nach Nettopreis: "
    "<=250 € 'werkzeug', 250–800 € 'gwg', >800 € 'afa'. Lebensmittel/Privates = 'privat'. Restaurant = 'bewirtung'. "
    "Antwort nur als JSON nach Schema."
)

CAT_HELP = "Kategorien: " + "; ".join(f"{k} = {v[0]}" for k, v in CATEGORIES.items())


def _img_to_data_url(img: Image.Image, max_side: int = 1600) -> str:
    img = ImageOps.exif_transpose(img).convert("RGB")
    s = max(img.size)
    if s > max_side:
        img = img.resize((round(img.width * max_side / s), round(img.height * max_side / s)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=88)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def load_document(path: Path) -> tuple[list[Image.Image], str]:
    """Return (page images, text layer). PDFs: text layer + first 2 pages rendered."""
    suf = path.suffix.lower()
    if suf == ".pdf":
        import pypdfium2 as pdfium
        pdf = pdfium.PdfDocument(str(path))
        text = "\n".join(pdf[i].get_textpage().get_text_range() for i in range(min(len(pdf), 4)))
        imgs = [pdf[i].render(scale=2.0).to_pil() for i in range(min(len(pdf), 2))]
        return imgs, text.strip()
    return [Image.open(path)], ""


def preview_image(path: Path, out: Path) -> None:
    imgs, _ = load_document(path)
    im = ImageOps.exif_transpose(imgs[0]).convert("RGB")
    im.thumbnail((1400, 1400))
    im.save(out, "JPEG", quality=85)


def _chat(messages: list, timeout: int = 300) -> dict:
    body = {"model": MODEL, "messages": messages, "temperature": 0.1, "max_tokens": 1500,
            "response_format": {"type": "json_schema", "json_schema": {"name": "beleg", "strict": True, "schema": SCHEMA}}}
    req = urllib.request.Request(LMSTUDIO + "/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        resp = json.loads(r.read().decode("utf-8"))
    content = resp["choices"][0]["message"]["content"]
    content = re.sub(r"^```(json)?|```$", "", content.strip()).strip()
    return json.loads(content)


def extract(path: Path) -> dict:
    imgs, text = load_document(path)
    user: list = []
    if text and len(text) > 80:
        user.append({"type": "text", "text": "Textebene des PDF-Belegs:\n" + text[:6000]})
    for im in imgs[:2]:
        user.append({"type": "image_url", "image_url": {"url": _img_to_data_url(im)}})
    user.append({"type": "text", "text": "Extrahiere die Belegdaten. " + CAT_HELP})
    data = _chat([{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}])
    return postprocess(data)


def postprocess(d: dict) -> dict:
    """Arithmetic checks + Kleinunternehmer rules. Adds 'warnings'."""
    w = []
    gross = float(d.get("total_gross") or 0)
    lines = d.get("vat_lines") or []
    net = round(sum(float(x.get("net") or 0) for x in lines), 2)
    vat = round(sum(float(x.get("vat") or 0) for x in lines), 2)
    if lines and abs(net + vat - gross) > 0.03:
        w.append(f"Summe passt nicht: netto {net:.2f} + USt {vat:.2f} ≠ brutto {gross:.2f}")
    for x in lines:
        r, n, v = float(x.get("rate") or 0), float(x.get("net") or 0), float(x.get("vat") or 0)
        if n and abs(n * r / 100 - v) > 0.05:
            w.append(f"USt {r:g} %: {n:.2f} × {r:g} % ≠ {v:.2f}")
    if not lines:
        net = gross
    d["net_total"] = net
    d["vat_total"] = vat
    # Kleinunternehmer: no input-tax deduction -> the expense is the gross amount
    d["amount_eur"] = gross
    cat = d.get("category")
    if cat not in CATEGORIES:
        d["category"] = cat = "sonstige"
    if cat in ("werkzeug", "gwg", "afa") and net:
        if net > 800 and cat != "afa":
            w.append("Netto > 800 € – wahrscheinlich Anlagegut (AfA) statt Sofortabzug, bitte prüfen")
        elif 250 < net <= 800 and cat != "gwg":
            w.append("Netto 250–800 € – GWG-Verzeichnis führen, bitte prüfen")
    if cat == "bewirtung":
        w.append("Bewirtung: nur 70 % abziehbar; Anlass und Teilnehmer auf dem Beleg vermerken")
    if (d.get("currency") or "EUR").upper() not in ("EUR", "€"):
        w.append(f"Fremdwährung {d.get('currency')} – in EUR umrechnen")
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", d.get("date") or ""):
        w.append("Datum nicht erkannt")
    if float(d.get("confidence") or 0) < 0.7:
        w.append("Unsichere Erkennung – bitte genau prüfen")
    d["warnings"] = w
    return d


if __name__ == "__main__":
    import sys, time
    t = time.time()
    print(json.dumps(extract(Path(sys.argv[1])), ensure_ascii=False, indent=1))
    print(f"{time.time() - t:.1f} s")
