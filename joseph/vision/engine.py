"""visual osint evidence engine.

runs every channel independently, keeps the streams separate, and produces a graded
visual-evidence report. it never fuses a face match and a location into an identity
conclusion; it reports each channel's finding and, where channels corroborate, notes it as
a candidate hypothesis with explicit uncertainty.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .channels import DEFAULT_CHANNELS, ChannelResult, EvidenceChannel, CANNOT_RESOLVE


@dataclass
class VisualEvidence:
    channels: list[ChannelResult] = field(default_factory=list)
    location_hypothesis: dict | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "channels": [
                {
                    "channel": c.channel,
                    "status": c.status,
                    "observations": c.observations,
                    "reason": c.reason,
                    "confidence": c.confidence,
                }
                for c in self.channels
            ],
            "location_hypothesis": self.location_hypothesis,
            "notes": self.notes,
        }


def analyze_image(data: bytes, channels: tuple[EvidenceChannel, ...] = DEFAULT_CHANNELS) -> VisualEvidence:
    results = [ch.run(data) for ch in channels]
    ev = VisualEvidence(channels=results)

    # geographic hypothesis comes only from deterministic gps evidence (epistemic firewall:
    # this is an OBSERVATION from metadata, not an inference from appearance).
    geo = next((c for c in results if c.channel == "exif_geo" and c.status == "resolved"), None)
    if geo and "gps" in geo.observations:
        gps = geo.observations["gps"]
        ev.location_hypothesis = {
            "source": "image exif gps (observation)",
            "lat": gps.get("lat"),
            "lon": gps.get("lon"),
            "confidence": geo.confidence,
            "caveat": "metadata can be absent, stale, or edited; treat as a lead, not proof",
        }
    else:
        ev.notes.append("no location hypothesis -> exif gps absent (CANNOT_RESOLVE for geolocation)")

    disabled = [c.channel for c in results if c.status == CANNOT_RESOLVE and c.reason]
    if disabled:
        ev.notes.append("disabled/absent channels: " + ", ".join(disabled))
    return ev


async def enrich_with_compreface(data: bytes, ev: "VisualEvidence", cfg) -> "VisualEvidence":
    """replace the disabled face_recognition placeholder with a real result from the
    operator's own compreface instance, and append the compreface detection channel.
    called only when compreface env is configured -> default behavior is unchanged.
    """
    from . import compreface

    rec = await compreface.recognize(cfg, data)
    det = await compreface.detect(cfg, data)

    # swap the placeholder face_recognition channel for the live result
    replaced = False
    for i, c in enumerate(ev.channels):
        if c.channel == "face_recognition":
            ev.channels[i] = rec
            replaced = True
            break
    if not replaced:
        ev.channels.append(rec)
    ev.channels.append(det)
    return ev
