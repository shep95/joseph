"""evidence channels.

each channel produces one independent evidence stream from an image. channels return a
graded result, never a hard identity claim.

enabled (deterministic, non-ai, measures the image itself):
    - provenance      -> content hash / size / format
    - exif_geo        -> exif + gps when the file carries it
    - image           -> dimensions, format, dominant colors, screenshot heuristic
    - phash           -> perceptual hashes (near-duplicate / image-reuse detection)
    - face_detection  -> face presence / count / size / sharpness (NOT identity)

disabled by design (would require a learned model + a corpus you are authorized to search,
i.e. biometric recognition / surveillance -> joseph ships neither):
    - face_recognition (identity matching)
    - scene            (landmark / satellite geolocation against an imagery corpus)
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import imaging, faces
from .exif import parse_exif
from .provenance import analyze_provenance

CANNOT_RESOLVE = "CANNOT_RESOLVE"


@dataclass
class ChannelResult:
    channel: str
    status: str                 # resolved | partial | CANNOT_RESOLVE
    observations: dict = field(default_factory=dict)
    reason: str = ""
    confidence: float = 0.0


class EvidenceChannel:
    name = "base"

    def run(self, data: bytes) -> ChannelResult:  # pragma: no cover - interface
        raise NotImplementedError


class ProvenanceChannel(EvidenceChannel):
    name = "provenance"

    def run(self, data: bytes) -> ChannelResult:
        p = analyze_provenance(data)
        return ChannelResult(self.name, "resolved", p.to_dict(), confidence=1.0)


class ExifGeoChannel(EvidenceChannel):
    """real, deterministic geographic + metadata evidence from the file itself."""

    name = "exif_geo"

    def run(self, data: bytes) -> ChannelResult:
        ex = parse_exif(data)
        obs = {
            "make": ex.make,
            "model": ex.model,
            "datetime_original": ex.datetime_original or ex.datetime,
            "orientation": ex.orientation,
            "warnings": ex.warnings,
        }
        if ex.has_gps:
            obs["gps"] = {"lat": ex.gps_lat, "lon": ex.gps_lon, "alt": ex.gps_alt}
            obs["maps_url"] = f"https://www.openstreetmap.org/?mlat={ex.gps_lat}&mlon={ex.gps_lon}#map=16/{ex.gps_lat}/{ex.gps_lon}"
            return ChannelResult(self.name, "resolved", obs, confidence=0.9)
        if ex.has_exif:
            return ChannelResult(self.name, "partial", obs, reason="exif present but no gps tag", confidence=0.3)
        return ChannelResult(
            self.name, CANNOT_RESOLVE, obs,
            reason="no exif metadata -> screenshots, social-media uploads and re-encoded images are usually stripped; try an original camera photo with location on",
            confidence=0.0,
        )


class ImagePropertiesChannel(EvidenceChannel):
    name = "image"

    def run(self, data: bytes) -> ChannelResult:
        if not imaging.available():
            return ChannelResult(self.name, CANNOT_RESOLVE, {}, reason="pillow not installed", confidence=0.0)
        m = imaging.measure(data)
        if m is None:
            return ChannelResult(self.name, CANNOT_RESOLVE, {}, reason="could not decode image", confidence=0.0)
        d = m.to_dict()
        return ChannelResult(self.name, "resolved", d, confidence=1.0)


class PerceptualHashChannel(EvidenceChannel):
    name = "phash"

    def run(self, data: bytes) -> ChannelResult:
        if not imaging.available():
            return ChannelResult(self.name, CANNOT_RESOLVE, {}, reason="pillow/numpy not installed", confidence=0.0)
        m = imaging.measure(data)
        if m is None:
            return ChannelResult(self.name, CANNOT_RESOLVE, {}, reason="could not decode image", confidence=0.0)
        obs = {"ahash": m.ahash, "dhash": m.dhash, "phash": m.phash,
               "use": "compare against a known-image set with hamming distance to detect reuse/near-duplicates"}
        return ChannelResult(self.name, "resolved", obs, confidence=0.9)


class FaceDetectionChannel(EvidenceChannel):
    """classical detection -> measures face presence/size/quality. never identity."""

    name = "face_detection"

    def run(self, data: bytes) -> ChannelResult:
        if not faces.available():
            return ChannelResult(
                self.name, CANNOT_RESOLVE, {},
                reason="opencv not installed -> add opencv-python-headless to enable face detection (detection only, no identity)",
                confidence=0.0,
            )
        fm = faces.detect(data)
        if fm is None:
            return ChannelResult(self.name, CANNOT_RESOLVE, {}, reason="could not decode image", confidence=0.0)
        obs = fm.to_dict()
        obs["note"] = "detection/measurement only -> not matched to any identity or corpus"
        status = "resolved" if fm.count else "partial"
        return ChannelResult(self.name, status, obs, confidence=0.8 if fm.count else 0.4)


class _DisabledChannel(EvidenceChannel):
    reason = "backend not enabled"

    def run(self, data: bytes) -> ChannelResult:
        return ChannelResult(self.name, CANNOT_RESOLVE, {}, reason=self.reason, confidence=0.0)


class FaceRecognitionChannel(_DisabledChannel):
    name = "face_recognition"
    reason = "identity matching is disabled by design -> would require a learned face model and a corpus you are authorized to search (biometric surveillance); joseph ships neither. face_detection measures faces without identifying them"


class SceneChannel(_DisabledChannel):
    name = "scene"
    reason = "scene/landmark geolocation is disabled by design -> requires an authorized geospatial imagery corpus and a matcher; gps from exif_geo is the supported location channel"


DEFAULT_CHANNELS: tuple[EvidenceChannel, ...] = (
    ProvenanceChannel(),
    ImagePropertiesChannel(),
    ExifGeoChannel(),
    PerceptualHashChannel(),
    FaceDetectionChannel(),
    FaceRecognitionChannel(),
    SceneChannel(),
)
