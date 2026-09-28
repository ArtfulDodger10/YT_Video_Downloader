"""Regenerate ytdown/assets/icon.png and icon.ico (needs Pillow: pip install pillow)."""

from pathlib import Path

from PIL import Image, ImageDraw

S = 1024
OUT = Path(__file__).resolve().parent.parent / "ytdown" / "assets"


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def make() -> Image.Image:
    top, bottom = (138, 108, 255), (64, 140, 255)
    grad = Image.new("RGB", (S, S))
    px = grad.load()
    for y in range(S):
        for x in range(S):
            px[x, y] = lerp(top, bottom, (x * 0.35 + y * 0.65) / S)
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle((40, 40, S - 40, S - 40), radius=230, fill=255)
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    img.paste(grad, (0, 0), mask)

    d = ImageDraw.Draw(img)
    white = (255, 255, 255, 255)
    cx = S // 2
    d.rounded_rectangle((cx - 62, 230, cx + 62, 560), radius=40, fill=white)  # shaft
    d.polygon([(cx - 215, 470), (cx + 215, 470), (cx, 700)], fill=white)  # head
    d.rounded_rectangle((250, 760, S - 250, 850), radius=45, fill=white)  # tray
    return img


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    big = make()
    big.resize((256, 256), Image.LANCZOS).save(OUT / "icon.png")
    big.resize((256, 256), Image.LANCZOS).save(
        OUT / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("wrote", OUT)
