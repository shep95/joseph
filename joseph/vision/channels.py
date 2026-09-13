"""evidence channels.

each channel produces one independent evidence stream from an image. channels return a
graded result, never a hard identity claim. the biometric / scene / perceptual-hash
channels are intentionally NOT implemented -> they require an explicitly authorized model
backend and corpus that joseph does not ship. they return CANNOT_RESOLVE with a reason so
the system is honest about what it can and cannot do.
"""

from __future__ import annotations

from dataclasses import dataclass, field

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
        return ChannelResult(
            channel=self.name,
            status="resolved",
            observations=p.to_dict(),
            confidence=1.0,
        )


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
            return ChannelResult(self.name, "partial", obs, reason="exif present but no gps", confidence=0.3)
        return ChannelResult(self.name, CANNOT_RESOLVE, obs, reason="no exif metadata", confidence=0.0)


class _DisabledChannel(EvidenceChannel):
    """a channel whose backend is not shipped. always CANNOT_RESOLVE, by design."""

    reason = "backend not enabled"

    def run(self, data: bytes) -> ChannelResult:
        return ChannelResult(self.name, CANNOT_RESOLVE, {}, reason=self.reason, confidence=0.0)


class FaceChannel(_DisabledChannel):
    name = "face"
    reason = "biometric face matching is disabled -> requires an explicitly authorized model backend and a corpus you are permitted to search; joseph ships neither"


class SceneChannel(_DisabledChannel):
    name = "scene"
    reason = "scene/landmark geolocation backend not enabled -> requires an authorized geospatial imagery corpus"


class PerceptualHashChannel(_DisabledChannel):
    name = "phash"
    reason = "perceptual hashing backend not enabled -> requires image decoding (optional dependency)"


DEFAULT_CHANNELS: tuple[EvidenceChannel, ...] = (
    ProvenanceChannel(),
    ExifGeoChannel(),
    FaceChannel(),
    SceneChannel(),
    PerceptualHashChannel(),
)
