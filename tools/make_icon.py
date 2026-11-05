"""Build assets/labalab.ico (16-256 px) from the LabaLab mark.

    python tools/make_icon.py

The icon is the camel-and-robot mark on a transparent square. At 16-24 px the
whole mark is an orange smear, so those sizes show only the robot.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "docs" / "design" / "img" / "labalab-mark.png"
OUT = ROOT / "assets" / "labalab.ico"
SIZES = (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)
SMALL = 24          # this size and below: the robot only


def _square(mark: Image.Image, size: int, pad: float) -> Image.Image:
    """Fit `mark` into a transparent size x size square, centred."""
    box = size * (1 - 2 * pad)
    scale = min(box / mark.width, box / mark.height)
    w, h = max(1, round(mark.width * scale)), max(1, round(mark.height * scale))
    fitted = mark.resize((w, h), Image.LANCZOS)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(fitted, ((size - w) // 2, (size - h) // 2), fitted)
    return out


def _robot_only(mark: Image.Image) -> Image.Image:
    """The robot is the right third of the mark. The camel's nose pokes into
    that third too, so keep only the shape connected to the robot's body."""
    part = mark.crop((int(mark.width * 0.66), 0, mark.width, mark.height))
    alpha = part.getchannel("A")
    solid = alpha.point(lambda a: 255 if a > 128 else 0)
    centre = (int(part.width * 0.6), int(part.height * 0.85))   # the robot's body
    ImageDraw.floodfill(solid, centre, 128)
    keep = solid.point(lambda v: 255 if v == 128 else 0).filter(ImageFilter.MaxFilter(3))
    part.putalpha(ImageChops.multiply(alpha, keep))
    return part.crop(part.getbbox())


def build() -> Path:
    mark = Image.open(SRC).convert("RGBA")
    mark = mark.crop(mark.getbbox())
    robot = _robot_only(mark)
    frames = [_square(robot if s <= SMALL else mark, s, 0.03 if s <= SMALL else 0.02)
              for s in SIZES]
    big = frames[-1]
    big.save(OUT, format="ICO", sizes=[(s, s) for s in SIZES],
             append_images=frames[:-1])
    return OUT


if __name__ == "__main__":
    print(build())
