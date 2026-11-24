"""Minimal, dependency-free reader for FL Studio .flp project files.

Only pulls what the namer needs: tempo, project-info title and FL version.

FLP layout: b"FLhd" + u32 len + (i16 format, u16 channels, u16 ppq),
then b"FLdt" + u32 len + an event stream. Event size comes from the ID:
  0-63 -> 1 byte, 64-127 -> 2 bytes, 128-191 -> 4 bytes, 192+ -> varint length + payload.
FL 2026 breaks that rule for event 172 (it is 1 byte, not 4). Parsers that
don't know this desync and can miss the tempo, so we parse both ways and
keep the most plausible answer.

Tempo:  event 156 (u32, BPM x 1000). Older files: 66 (u16 whole BPM) + 93 (u16 milli-BPM).
        No tempo event at all = FL's default tempo (140).
Title:  event 194 (UTF-16LE in FL 11.5+, ASCII before).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

EV_TEMPO = 156
EV_TEMPO_COARSE = 66
EV_TEMPO_FINE = 93
EV_TITLE = 194
EV_VERSION = 199
EV_GENRE = 206
FL_DEFAULT_TEMPO = 140.0

SIZE_OVERRIDES_FL2026 = {172: 1}


class FlpError(ValueError):
    pass


@dataclass
class FlpInfo:
    tempo: float | None          # BPM, None if it couldn't be read
    tempo_source: str            # "project", "legacy", "default", "unreadable"
    title: str = ""
    genre: str = ""
    fl_version: str = ""


def _event_stream(data: bytes) -> memoryview:
    if data[:4] != b"FLhd":
        raise FlpError("not an FLP file")
    hd_len = int.from_bytes(data[4:8], "little")
    dt = 8 + hd_len
    if data[dt:dt + 4] != b"FLdt":
        raise FlpError("no FLdt chunk")
    dt_len = int.from_bytes(data[dt + 4:dt + 8], "little")
    start = dt + 8
    # Be lenient: a truncated file (still being written) just yields what's there.
    return memoryview(data)[start:min(start + dt_len, len(data))]


def _iter_events(stream: memoryview, overrides: dict[int, int]):
    i, n = 0, len(stream)
    while i < n:
        eid = stream[i]
        i += 1
        if eid in overrides:
            size = overrides[eid]
        elif eid < 64:
            size = 1
        elif eid < 128:
            size = 2
        elif eid < 192:
            size = 4
        else:
            size, shift = 0, 0
            while i < n:
                b = stream[i]
                i += 1
                size |= (b & 0x7F) << shift
                shift += 7
                if not b & 0x80:
                    break
        if i + size > n:
            return
        yield eid, stream[i:i + size]
        i += size


def _decode_text(raw: bytes) -> str:
    raw = bytes(raw)
    if len(raw) >= 2 and raw[1:2] == b"\x00":  # UTF-16LE (FL 11.5+)
        txt = raw.decode("utf-16-le", errors="ignore")
    else:
        txt = raw.decode("latin-1", errors="ignore")
    return txt.replace("\x00", "").strip()


def _scan(stream: memoryview, overrides: dict[int, int]) -> dict:
    out: dict = {}
    for eid, payload in _iter_events(stream, overrides):
        if eid == EV_TEMPO and len(payload) == 4 and "tempo" not in out:
            out["tempo"] = int.from_bytes(payload, "little") / 1000
        elif eid == EV_TEMPO_COARSE and len(payload) == 2 and "coarse" not in out:
            out["coarse"] = int.from_bytes(payload, "little")
        elif eid == EV_TEMPO_FINE and len(payload) == 2 and "fine" not in out:
            out["fine"] = int.from_bytes(payload, "little")
        elif eid == EV_TITLE and "title" not in out:
            out["title"] = _decode_text(payload)
        elif eid == EV_GENRE and "genre" not in out:
            out["genre"] = _decode_text(payload)
        elif eid == EV_VERSION and "version" not in out:
            out["version"] = bytes(payload).split(b"\x00")[0].decode("ascii", "ignore")
    return out


def _plausible(bpm) -> bool:
    return bpm is not None and 10 <= bpm <= 999


def read_flp(path: str | Path) -> FlpInfo:
    data = Path(path).read_bytes()
    stream = _event_stream(data)

    # Try the FL-2026-aware parse first, then the classic one.
    results = [_scan(stream, SIZE_OVERRIDES_FL2026), _scan(stream, {})]

    for res in results:
        if _plausible(res.get("tempo")):
            return FlpInfo(round(res["tempo"], 3), "project", res.get("title", ""),
                           res.get("genre", ""), res.get("version", ""))
    for res in results:
        if "coarse" in res:
            bpm = res["coarse"] + res.get("fine", 0) / 1000
            if _plausible(bpm):
                return FlpInfo(round(bpm, 3), "legacy", res.get("title", ""),
                               res.get("genre", ""), res.get("version", ""))

    best = results[0]
    # Both parses walked the whole file and found no tempo event: FL omits it
    # when the project sits at the default tempo.
    if best.get("version"):
        return FlpInfo(FL_DEFAULT_TEMPO, "default", best.get("title", ""),
                       best.get("genre", ""), best.get("version", ""))
    return FlpInfo(None, "unreadable", best.get("title", ""), best.get("genre", ""), "")


if __name__ == "__main__":
    import sys
    for p in sys.argv[1:]:
        print(p, read_flp(p))
