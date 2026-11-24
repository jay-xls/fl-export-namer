import struct

import pytest

from flp_reader import FlpError, read_flp


def varint(n):
    out = b""
    while True:
        b, n = n & 0x7F, n >> 7
        out += bytes([b | (0x80 if n else 0)])
        if not n:
            return out


def ev(eid, payload):
    return bytes([eid]) + (varint(len(payload)) if eid >= 192 else b"") + payload


def flp(path, *events):
    data = b"".join(events)
    path.write_bytes(b"FLhd" + struct.pack("<IhHH", 6, 0, 10, 96) + b"FLdt" + struct.pack("<I", len(data)) + data)
    return path


VER = ev(199, b"26.1.5.5618\x00")
TITLE = ev(194, "Nightdrive".encode("utf-16-le") + b"\0\0")


def test_fl2026_one_byte_event_172_before_tempo(tmp_path):
    # A classic parser reads event 172 as 4 bytes, desyncs and loses the tempo.
    info = read_flp(flp(tmp_path / "a.flp", VER, bytes([172, 5]), ev(156, struct.pack("<I", 142500)), TITLE))
    assert (info.tempo, info.tempo_source, info.title) == (142.5, "project", "Nightdrive")


def test_legacy_coarse_fine_tempo(tmp_path):
    info = read_flp(flp(tmp_path / "c.flp", ev(199, b"9.0.0\x00"), ev(66, struct.pack("<H", 128)),
                        ev(93, struct.pack("<H", 500))))
    assert (info.tempo, info.tempo_source) == (128.5, "legacy")


def test_missing_tempo_means_fl_default(tmp_path):
    info = read_flp(flp(tmp_path / "d.flp", VER, TITLE))
    assert (info.tempo, info.tempo_source) == (140.0, "default")


def test_not_an_flp(tmp_path):
    p = tmp_path / "e.flp"
    p.write_bytes(b"nope")
    with pytest.raises(FlpError):
        read_flp(p)
