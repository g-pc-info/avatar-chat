import sys
from pathlib import Path
from PIL import Image

root = Path(__file__).resolve().parent.parent
order = ["neutral", "happy", "sad", "angry", "surprised", "embarrassed", "thinking", "sleepy"]
for cid in ("honoka", "rei"):
    d = root / "characters" / f"builtin_{cid}"
    tiles = [Image.open(d / f"{n}.webp").convert("RGBA") for n in order]
    w, h = 256, 374
    sheet = Image.new("RGB", (w * 4, h * 2), (225, 232, 245))
    for i, t in enumerate(tiles):
        t.thumbnail((w, h))
        sheet.paste(t, ((i % 4) * w + (w - t.width) // 2, (i // 4) * h), t)
    (root / "misc" / "gen").mkdir(parents=True, exist_ok=True)
    sheet.save(root / "misc" / "gen" / f"{cid}_sheet.png")
    print("sheet", cid, [im.size for im in tiles][:1])
