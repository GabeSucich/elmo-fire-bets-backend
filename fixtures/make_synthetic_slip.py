import pathlib

from PIL import Image, ImageDraw, ImageFont

W, H = 900, 1150
img = Image.new("RGB", (W, H), "#14161c")
d = ImageDraw.Draw(img)

def font(sz, bold=False):
    path = "/System/Library/Fonts/Helvetica.ttc"
    return ImageFont.truetype(path, sz, index=1 if bold else 0)

y = 40
d.text((40, y), "5 Leg Parlay", font=font(38, True), fill="white"); y += 55
# The repeated header summary the prompt must ignore.
d.text((40, y), "Over 0.5, 2+, Over 11.5, 42+, Over 216.5", font=font(24), fill="#8b90a0"); y += 40
d.text((40, y), "+1450   |   $25 to win $362.50", font=font(24), fill="#8b90a0"); y += 60

d.line((40, y, W - 40, y), fill="#2c3040", width=2); y += 35

LEGS = [
    ("Travis Kelce", "Anytime Touchdown Scorer", "Over 0.5"),
    ("LAC Total Field Goals", "Total Field Goals", "2+"),
    ("Isiah Pacheco", "Receiving Yards", "Over 11.5"),
    ("Rashee Rice", "Rushing Yards", "42+"),
    ("Patrick Mahomes", "Passing Yards", "Over 216.5"),
]

for name, market, line in LEGS:
    d.text((40, y), name, font=font(30, True), fill="white"); y += 42
    d.text((40, y), market, font=font(25), fill="#b8bdcc"); y += 38
    d.text((40, y), line, font=font(27, True), fill="#5aa9ff"); y += 45
    d.line((40, y, W - 40, y), fill="#2c3040", width=1); y += 30

out = pathlib.Path(__file__).parent / "synthetic_slip.png"
img.save(out)
print(f"wrote {out}")
