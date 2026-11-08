"""生成した立ち絵PNGから、白背景を透明にして WebP(768px以内)にする。
使い方: python3 misc/make_sprites.py <PNGのフォルダ> <出力フォルダ>
PNGに埋め込まれるワークフロー情報(プロンプトなど)は、WebPへの変換で消える。
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

MARK = (255, 0, 255)


def cut_background(im: Image.Image, thresh: int = 22) -> Image.Image:
    rgb = im.convert("RGB")
    w, h = rgb.size
    work = rgb.copy()
    for xy in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
        if work.getpixel(xy) != MARK:
            ImageDraw.floodfill(work, xy, MARK, thresh=thresh)
    mask = Image.new("L", (w, h), 255)
    px, mp = work.load(), mask.load()
    for y in range(h):
        for x in range(w):
            if px[x, y] == MARK:
                mp[x, y] = 0
    mask = mask.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(0.8))
    out = rgb.convert("RGBA")
    out.putalpha(mask)
    return out


def main():
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    dst.mkdir(parents=True, exist_ok=True)
    for f in sorted(src.glob("*.png")):
        im = cut_background(Image.open(f))
        im.thumbnail((768, 768), Image.LANCZOS)
        im.save(dst / (f.stem + ".webp"), "WEBP", quality=90)
        print("ok", f.name, im.size)


if __name__ == "__main__":
    main()
