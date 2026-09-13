"""deterministic image measurement -> properties, perceptual hashes, dominant colors.

all non-ai: fixed resampling, pure arithmetic. these measure the image itself (never
identity). perceptual hashes enable near-duplicate / image-reuse detection, which is the
honest, useful core of visual osint.

pillow + numpy are required for this module; callers guard the import so the bot still
runs if they are missing.
"""

from __future__ import annotations

import io
from collections import Counter
from dataclasses import dataclass, field

try:
    import numpy as np
    from PIL import Image

    _OK = True
except Exception:  # pragma: no cover - import guard
    _OK = False


def available() -> bool:
    return _OK


@dataclass
class ImageMeasurement:
    width: int
    height: int
    fmt: str
    mode: str
    megapixels: float
    aspect_ratio: float
    likely_screenshot: bool
    dominant_colors: list[dict] = field(default_factory=list)
    ahash: str = ""
    dhash: str = ""
    phash: str = ""

    def to_dict(self) -> dict:
        return {
            "width": self.width,
            "height": self.height,
            "format": self.fmt,
            "mode": self.mode,
            "megapixels": round(self.megapixels, 3),
            "aspect_ratio": round(self.aspect_ratio, 4),
            "likely_screenshot": self.likely_screenshot,
            "dominant_colors": self.dominant_colors,
            "perceptual_hashes": {"ahash": self.ahash, "dhash": self.dhash, "phash": self.phash},
        }


# common screen resolutions -> a weak signal that an image is a screenshot / capture
_SCREEN_SIZES = {
    (1920, 1080), (1366, 768), (1536, 864), (1280, 720), (1440, 900), (1600, 900),
    (2560, 1440), (3840, 2160), (1170, 2532), (1179, 2556), (1290, 2796), (1080, 1920),
    (828, 1792), (750, 1334), (1284, 2778), (1080, 2340), (1440, 3200),
}


def _to_gray_array(img, size):
    g = img.convert("L").resize(size, Image.Resampling.LANCZOS)
    return np.asarray(g, dtype=np.float64)


def _bits_to_hex(bits) -> str:
    val = 0
    for b in bits.flatten():
        val = (val << 1) | int(b)
    width = (bits.size + 3) // 4
    return format(val, "0{}x".format(width))


def _ahash(img) -> str:
    a = _to_gray_array(img, (8, 8))
    return _bits_to_hex(a > a.mean())


def _dhash(img) -> str:
    a = _to_gray_array(img, (9, 8))  # 9 wide -> 8 horizontal diffs per row
    diff = a[:, 1:] > a[:, :-1]
    return _bits_to_hex(diff)


def _dct2(a):
    # 2d dct-II via matrix multiply (deterministic, no scipy)
    n = a.shape[0]
    k = np.arange(n)
    basis = np.cos(np.pi * (2 * k[:, None] + 1) * k[None, :] / (2 * n))
    return basis @ a @ basis.T


def _phash(img) -> str:
    a = _to_gray_array(img, (32, 32))
    d = _dct2(a)
    low = d[:8, :8]
    med = np.median(low[1:, 1:])  # exclude the dc term from the median
    return _bits_to_hex(low > med)


def _dominant_colors(img, k: int = 5) -> list[dict]:
    rgb = img.convert("RGB").resize((64, 64), Image.Resampling.LANCZOS)
    pixels = list(rgb.getdata())
    counts = Counter(pixels)
    total = sum(counts.values())
    out = []
    for (r, g, b), c in counts.most_common(k):
        out.append({"hex": "#{:02x}{:02x}{:02x}".format(r, g, b), "share": round(c / total, 3)})
    return out


def measure(data: bytes) -> ImageMeasurement | None:
    if not _OK:
        return None
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception:
        return None
    w, h = img.size
    fmt = (img.format or "").lower()
    likely = (w, h) in _SCREEN_SIZES or (h, w) in _SCREEN_SIZES
    return ImageMeasurement(
        width=w,
        height=h,
        fmt=fmt,
        mode=img.mode,
        megapixels=(w * h) / 1_000_000,
        aspect_ratio=(w / h) if h else 0.0,
        likely_screenshot=likely,
        dominant_colors=_dominant_colors(img),
        ahash=_ahash(img),
        dhash=_dhash(img),
        phash=_phash(img),
    )


def hamming_hex(a: str, b: str) -> int:
    """hamming distance between two equal-length hex hashes -> near-duplicate metric."""
    if not a or not b or len(a) != len(b):
        return -1
    return bin(int(a, 16) ^ int(b, 16)).count("1")
