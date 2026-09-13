"""dependency-free exif + gps reader for jpeg/tiff bytes.

parses the exif tiff structure directly (no pillow, no piexif) so it runs anywhere and is
fully deterministic. extracts camera make/model, capture timestamp, orientation, and gps
coordinates when present. gps in image metadata is real, primary location evidence.

this reads only what the file itself carries. absent gps is reported as CANNOT_RESOLVE,
never guessed.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

# tag ids
_GPS_IFD = 0x8825
_EXIF_IFD = 0x8769
_MAKE = 0x010F
_MODEL = 0x0110
_ORIENTATION = 0x0112
_DATETIME = 0x0132
_DATETIME_ORIGINAL = 0x9003

# gps sub-tags
_GPS_LAT_REF = 1
_GPS_LAT = 2
_GPS_LON_REF = 3
_GPS_LON = 4
_GPS_ALT_REF = 5
_GPS_ALT = 6

_TYPE_SIZES = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 7: 1, 9: 4, 10: 8}


@dataclass
class ExifData:
    has_exif: bool = False
    make: str = ""
    model: str = ""
    orientation: int | None = None
    datetime: str = ""
    datetime_original: str = ""
    gps_lat: float | None = None
    gps_lon: float | None = None
    gps_alt: float | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def has_gps(self) -> bool:
        return self.gps_lat is not None and self.gps_lon is not None


def _find_exif_segment(data: bytes) -> bytes | None:
    """locate the APP1 Exif payload (the tiff block) inside a jpeg."""
    if data[:2] != b"\xff\xd8":  # not a jpeg SOI
        # maybe raw tiff
        if data[:2] in (b"II", b"MM"):
            return data
        return None
    i = 2
    n = len(data)
    while i + 4 <= n:
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xD8, 0xD9):
            i += 2
            continue
        if 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        seg_len = struct.unpack(">H", data[i + 2 : i + 4])[0]
        seg_start = i + 4
        seg_end = i + 2 + seg_len
        if marker == 0xE1:  # APP1
            payload = data[seg_start:seg_end]
            if payload[:6] == b"Exif\x00\x00":
                return payload[6:]
        if marker == 0xDA:  # start of scan -> no more metadata
            break
        i = seg_end
    return None


def _rationals_to_degrees(vals: list[float]) -> float | None:
    if len(vals) < 3:
        return None
    deg, minutes, seconds = vals[0], vals[1], vals[2]
    return deg + minutes / 60.0 + seconds / 3600.0


def _read_ifd(tiff: bytes, offset: int, endian: str) -> tuple[dict, int]:
    """read one ifd -> {tag: (type, count, value_bytes_or_offset)} and next-ifd offset."""
    entries: dict[int, tuple[int, int, bytes]] = {}
    if offset + 2 > len(tiff):
        return entries, 0
    count = struct.unpack(endian + "H", tiff[offset : offset + 2])[0]
    pos = offset + 2
    for _ in range(count):
        if pos + 12 > len(tiff):
            break
        tag, typ, cnt = struct.unpack(endian + "HHI", tiff[pos : pos + 8])
        value_field = tiff[pos + 8 : pos + 12]
        size = _TYPE_SIZES.get(typ, 1) * cnt
        if size <= 4:
            raw = value_field[:size]
        else:
            voff = struct.unpack(endian + "I", value_field)[0]
            raw = tiff[voff : voff + size]
        entries[tag] = (typ, cnt, raw)
        pos += 12
    next_off = 0
    if pos + 4 <= len(tiff):
        next_off = struct.unpack(endian + "I", tiff[pos : pos + 4])[0]
    return entries, next_off


def _decode_ascii(raw: bytes) -> str:
    return raw.split(b"\x00", 1)[0].decode("ascii", "ignore").strip()


def _decode_rationals(raw: bytes, endian: str, count: int) -> list[float]:
    out: list[float] = []
    for i in range(count):
        chunk = raw[i * 8 : i * 8 + 8]
        if len(chunk) < 8:
            break
        num, den = struct.unpack(endian + "II", chunk)
        out.append(num / den if den else 0.0)
    return out


def parse_exif(data: bytes) -> ExifData:
    out = ExifData()
    tiff = _find_exif_segment(data)
    if tiff is None or len(tiff) < 8:
        out.warnings.append("no exif segment present")
        return out
    out.has_exif = True

    if tiff[:2] == b"II":
        endian = "<"
    elif tiff[:2] == b"MM":
        endian = ">"
    else:
        out.warnings.append("unrecognized tiff byte order")
        return out

    ifd0_off = struct.unpack(endian + "I", tiff[4:8])[0]
    ifd0, _ = _read_ifd(tiff, ifd0_off, endian)

    if _MAKE in ifd0:
        out.make = _decode_ascii(ifd0[_MAKE][2])
    if _MODEL in ifd0:
        out.model = _decode_ascii(ifd0[_MODEL][2])
    if _ORIENTATION in ifd0:
        raw = ifd0[_ORIENTATION][2]
        if len(raw) >= 2:
            out.orientation = struct.unpack(endian + "H", raw[:2])[0]
    if _DATETIME in ifd0:
        out.datetime = _decode_ascii(ifd0[_DATETIME][2])

    # exif sub-ifd for DateTimeOriginal
    if _EXIF_IFD in ifd0:
        eoff = struct.unpack(endian + "I", ifd0[_EXIF_IFD][2])[0]
        exif_ifd, _ = _read_ifd(tiff, eoff, endian)
        if _DATETIME_ORIGINAL in exif_ifd:
            out.datetime_original = _decode_ascii(exif_ifd[_DATETIME_ORIGINAL][2])

    # gps sub-ifd
    if _GPS_IFD in ifd0:
        goff = struct.unpack(endian + "I", ifd0[_GPS_IFD][2])[0]
        gps_ifd, _ = _read_ifd(tiff, goff, endian)
        lat = _decode_rationals(gps_ifd[_GPS_LAT][2], endian, gps_ifd[_GPS_LAT][1]) if _GPS_LAT in gps_ifd else []
        lon = _decode_rationals(gps_ifd[_GPS_LON][2], endian, gps_ifd[_GPS_LON][1]) if _GPS_LON in gps_ifd else []
        lat_deg = _rationals_to_degrees(lat)
        lon_deg = _rationals_to_degrees(lon)
        if lat_deg is not None and lon_deg is not None:
            lat_ref = _decode_ascii(gps_ifd[_GPS_LAT_REF][2]) if _GPS_LAT_REF in gps_ifd else "N"
            lon_ref = _decode_ascii(gps_ifd[_GPS_LON_REF][2]) if _GPS_LON_REF in gps_ifd else "E"
            if lat_ref.upper().startswith("S"):
                lat_deg = -lat_deg
            if lon_ref.upper().startswith("W"):
                lon_deg = -lon_deg
            out.gps_lat = round(lat_deg, 7)
            out.gps_lon = round(lon_deg, 7)
        if _GPS_ALT in gps_ifd:
            alt = _decode_rationals(gps_ifd[_GPS_ALT][2], endian, gps_ifd[_GPS_ALT][1])
            if alt:
                out.gps_alt = round(alt[0], 2)
    else:
        out.warnings.append("no gps ifd present")

    return out
