"""content provenance for an uploaded media object.

deterministic, dependency-free: content hash, byte size, and a format sniff from magic
bytes. this is the chain-of-custody anchor for any visual evidence.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass


def _sniff_format(data: bytes) -> str:
    if data[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[:2] in (b"II", b"MM"):
        return "tiff"
    if data[:4] == b"%PDF":
        return "pdf"
    return "unknown"


@dataclass
class Provenance:
    sha256: str
    size_bytes: int
    media_format: str

    def to_dict(self) -> dict:
        return {"sha256": self.sha256, "size_bytes": self.size_bytes, "format": self.media_format}


def analyze_provenance(data: bytes) -> Provenance:
    return Provenance(
        sha256=hashlib.sha256(data).hexdigest(),
        size_bytes=len(data),
        media_format=_sniff_format(data),
    )
