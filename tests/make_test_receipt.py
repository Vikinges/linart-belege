"""Synthetic German receipt (Kassenbon) for testing - no real personal data."""
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import random, sys

out = sys.argv[1] if len(sys.argv) > 1 else "test_bon.jpg"
W, H = 560, 980
img = Image.new("RGB", (W, H), (250, 248, 242))
d = ImageDraw.Draw(img)
try:
    f = ImageFont.truetype("consola.ttf", 20)
    fb = ImageFont.truetype("consolab.ttf", 26)
except Exception:
    f = fb = ImageFont.load_default()
lines = [
    ("BAUHAUS Fachcentrum", fb), ("Musterstr. 12, 90402 Nürnberg", f), ("USt-IdNr. DE123456789", f), ("", f),
    ("Beleg-Nr. 4711-0815      06.11.2026", f), ("Kasse 3   Bed. 17       14:32", f), ("-" * 38, f),
    ("Kabelkanal 40x60 2m    2 x 6,99", f), ("                          13,98 A", f),
    ("Schrauben-Set Edelst.         8,49 A", f), ("Lötzinn 0,8mm 100g          12,95 A", f),
    ("WAGO 221-413 50 St.          24,90 A", f), ("-" * 38, f),
    ("SUMME EUR                   60,32", fb), ("", f),
    ("A 19,0%  Netto 50,69  MwSt 9,63", f), ("Brutto                      60,32", f), ("", f),
    ("Gegeben girocard            60,32", f), ("Kartenzahlung  ****1234", f), ("", f),
    ("Vielen Dank für Ihren Einkauf!", f), ("TSE-Signatur: 8f3a...c21e", f),
]
y = 30
for text, font in lines:
    w = d.textlength(text, font=font)
    x = (W - w) / 2 if font is fb or text.startswith(("BAUHAUS", "Muster", "USt", "Vielen")) else 30
    d.text((x, y), text, fill=(25, 25, 25), font=font)
    y += 34 if font is fb else 30
img = img.rotate(random.uniform(-2.5, 2.5), expand=True, fillcolor=(120, 110, 100)).filter(ImageFilter.GaussianBlur(0.6))
img.save(out, quality=82)
print(out)
