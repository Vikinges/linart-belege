"""Synthetic outgoing invoice from LinArt Labs (Kleinunternehmer) as PDF - test data only."""
from PIL import Image, ImageDraw, ImageFont
import sys
out = sys.argv[1]
W, H = 1240, 1754
im = Image.new("RGB", (W, H), "white")
d = ImageDraw.Draw(im)
try:
    F = lambda s: ImageFont.truetype("arial.ttf", s)
    FB = lambda s: ImageFont.truetype("arialbd.ttf", s)
except Exception:
    F = FB = lambda s: ImageFont.load_default()
d.text((100, 90), "LinArt Labs", font=FB(48), fill="black")
d.text((100, 150), "Max Mustermann · Musterweg 1 · 91000 Musterstadt", font=F(22), fill="black")
d.text((100, 300), "Testkunde GmbH\nBeispielstraße 5\n90402 Nürnberg", font=F(28), fill="black", spacing=8)
d.text((760, 300), "Rechnung Nr. 2026-0042\nDatum: 03.11.2026\nLeistungsdatum: 31.10.2026", font=F(26), fill="black", spacing=8)
d.text((100, 520), "Rechnung", font=FB(40), fill="black")
y = 610
for pos, txt, amt in [("1", "Einrichtung IoT-Dashboard (ThingsBoard), 6 Std.", "390,00 €"),
                      ("2", "LinArt Air CO2-Sensor, Founders Edition", "60,00 €")]:
    d.text((100, y), pos, font=F(26), fill="black"); d.text((160, y), txt, font=F(26), fill="black")
    d.text((960, y), amt, font=F(26), fill="black"); y += 50
d.line((100, y + 10, 1140, y + 10), fill="black", width=2)
d.text((700, y + 30), "Gesamtbetrag:", font=FB(30), fill="black"); d.text((960, y + 30), "450,00 €", font=FB(30), fill="black")
d.text((100, y + 120), "Gemäß § 19 UStG wird keine Umsatzsteuer berechnet.", font=F(24), fill="black")
d.text((100, y + 170), "Zahlbar innerhalb von 14 Tagen per Überweisung.", font=F(24), fill="black")
im.save(out, "PDF", resolution=150)
print(out)
