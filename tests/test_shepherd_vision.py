"""tests for the shepherd symbolic engine + vision/exif layer. no network, no discord.

run: python tests/test_shepherd_vision.py
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from joseph.engine.seed import IdentitySeed
from joseph.shepherd.registry import load_registry
from joseph.shepherd.knowledge_graph import build_graph
from joseph.shepherd.router import route
from joseph.shepherd.pattern_engine import select_patterns
from joseph.shepherd.creator import Event, mine, classify, test_against_history as replay_history
from joseph.vision.exif import parse_exif
from joseph.vision.provenance import analyze_provenance
from joseph.vision.engine import analyze_image


def test_registry_loads_and_validates():
    reg = load_registry()
    assert len(reg.patterns) >= 5
    assert reg.validate() == []
    assert reg.taxonomy["totals"]["domains"] == 28
    assert reg.taxonomy["totals"]["subdomains"] == 274


def test_knowledge_graph_relations():
    g = build_graph()
    # identity.confirmation contradicts identity.false_match per its relations
    conflicts = g.conflicts("identity.confirmation")
    assert "identity.false_match" in conflicts


def test_router_classifies():
    r1 = route(IdentitySeed.build(name="John Smith"))
    assert r1.task_type == "person_research"
    r2 = route(IdentitySeed.build(domains="jsmith.dev"))
    assert r2.task_type == "domain_research"
    r3 = route(IdentitySeed.build(usernames="jsmith"))
    assert r3.task_type == "username_research"


def test_pattern_engine_maps_operations_to_strategies():
    seed = IdentitySeed.build(name="John Smith", organizations="Company X")
    r, applied = select_patterns(seed)
    assert applied, "expected patterns for a person_research task"
    # document discovery should map to document strategies
    doc = [p for p in applied if p.pattern.id == "research.document_discovery"]
    assert doc and any("document" in s or "org_document" in s for s in doc[0].strategies)


def test_pattern_creator_mines_sequences():
    events = [
        Event("query_username_direct", "KNO", "success"),
        Event("extract_profile_handles", "NET", "success"),
        Event("compare_identifier", "MEA", "success"),
        Event("query_username_direct", "KNO", "success"),
        Event("extract_profile_handles", "NET", "success"),
        Event("compare_identifier", "MEA", "success"),
    ]
    candidates = mine(events, min_support=2, n=3)
    assert candidates, "expected at least one mined candidate sequence"
    c = candidates[0]
    assert c.status == "candidate"          # never auto-promoted
    assert replay_history(c, events)  # sequence actually occurred
    assert classify(c) in {"research", "resolution", "audit", "general"}


def _build_exif_jpeg_with_gps() -> bytes:
    """construct a minimal little-endian tiff exif block with a gps ifd, wrapped in jpeg."""
    def entry(tag, typ, count, value4: bytes) -> bytes:
        assert len(value4) == 4
        return struct.pack("<HHI", tag, typ, count)[:8] + value4

    # external rationals: lat = 40/1, 26/1, 4680/100 ; lon = 79/1, 58/1, 5600/100
    gps_ifd_offset = 26
    lat_off = 80
    lon_off = 104
    lat_bytes = struct.pack("<IIIIII", 40, 1, 26, 1, 4680, 100)
    lon_bytes = struct.pack("<IIIIII", 79, 1, 58, 1, 5600, 100)

    # ifd0: one entry -> pointer to gps ifd
    ifd0 = struct.pack("<H", 1) + entry(0x8825, 4, 1, struct.pack("<I", gps_ifd_offset)) + struct.pack("<I", 0)

    gps_entries = b"".join([
        entry(1, 2, 2, b"N\x00\x00\x00"),               # GPSLatitudeRef
        entry(2, 5, 3, struct.pack("<I", lat_off)),       # GPSLatitude
        entry(3, 2, 2, b"E\x00\x00\x00"),               # GPSLongitudeRef
        entry(4, 5, 3, struct.pack("<I", lon_off)),       # GPSLongitude
    ])
    gps_ifd = struct.pack("<H", 4) + gps_entries + struct.pack("<I", 0)

    tiff = b"II" + struct.pack("<H", 42) + struct.pack("<I", 8)
    # pad tiff to gps_ifd_offset, then gps ifd, then rationals at their offsets
    body = ifd0
    assert len(tiff) + len(body) == gps_ifd_offset, (len(tiff), len(body))
    blob = tiff + body + gps_ifd
    # pad to lat_off
    blob = blob + b"\x00" * (lat_off - len(blob)) + lat_bytes
    blob = blob + b"\x00" * (lon_off - len(blob)) + lon_bytes

    payload = b"Exif\x00\x00" + blob
    app1 = b"\xff\xe1" + struct.pack(">H", len(payload) + 2) + payload
    return b"\xff\xd8" + app1 + b"\xff\xd9"


def test_exif_gps_extraction():
    jpeg = _build_exif_jpeg_with_gps()
    ex = parse_exif(jpeg)
    assert ex.has_exif
    assert ex.has_gps
    assert 40.0 < ex.gps_lat < 41.0
    assert 79.0 < ex.gps_lon < 80.0


def test_exif_absent_is_cannot_resolve():
    ex = parse_exif(b"\xff\xd8\xff\xd9")  # empty jpeg, no exif
    assert not ex.has_gps
    ev = analyze_image(b"\xff\xd8\xff\xd9")
    assert ev.location_hypothesis is None
    assert any("CANNOT_RESOLVE" in n or "no location" in n for n in ev.notes)


def test_provenance_format_sniff():
    assert analyze_provenance(b"\xff\xd8\xff\xe0rest").media_format == "jpeg"
    assert analyze_provenance(b"\x89PNG\r\n\x1a\nrest").media_format == "png"
    p = analyze_provenance(b"hello world")
    assert p.size_bytes == 11 and len(p.sha256) == 64


def _run_all() -> int:
    tests = [
        v for k, v in sorted(globals().items())
        if k.startswith("test_") and callable(v) and getattr(v, "__module__", "") == __name__
    ]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  ok   {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL {t.__name__}: {e}")
        except Exception as e:  # noqa
            failed += 1
            print(f"  ERR  {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_all())
