"""classical face DETECTION (not recognition).

uses opencv's haar cascade to measure whether faces are present, how many, how large, and
a sharpness estimate. this is visual evidence -> "a face is present here, this big, this
sharp" -> never an identity claim and never matched against any corpus.

opencv is optional; if it is not installed the channel degrades to unavailable rather than
crashing the bot.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field

try:
    import cv2
    import numpy as np
    from PIL import Image

    _CASCADE = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    _OK = not _CASCADE.empty()
except Exception:  # pragma: no cover - import guard
    _OK = False


def available() -> bool:
    return _OK


@dataclass
class FaceMeasurement:
    count: int
    faces: list[dict] = field(default_factory=list)
    image_sharpness: float = 0.0

    def to_dict(self) -> dict:
        return {"count": self.count, "faces": self.faces, "image_sharpness": round(self.image_sharpness, 2)}


def detect(data: bytes) -> FaceMeasurement | None:
    if not _OK:
        return None
    try:
        pil = Image.open(io.BytesIO(data)).convert("RGB")
    except Exception:
        return None
    arr = np.asarray(pil)
    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    h, w = gray.shape[:2]
    area = float(w * h) or 1.0

    boxes = _CASCADE.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(24, 24))
    faces = []
    for (x, y, fw, fh) in boxes:
        crop = gray[y : y + fh, x : x + fw]
        sharp = float(cv2.Laplacian(crop, cv2.CV_64F).var()) if crop.size else 0.0
        faces.append(
            {
                "box": [int(x), int(y), int(fw), int(fh)],
                "area_fraction": round((fw * fh) / area, 4),
                "sharpness": round(sharp, 2),
            }
        )
    faces.sort(key=lambda f: -f["area_fraction"])
    overall = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    return FaceMeasurement(count=len(faces), faces=faces, image_sharpness=overall)
