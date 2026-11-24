"""Minimal, dependency-free reader for Ableton Live sets (.als).

Only pulls what the namer needs: tempo, the set's key/scale and Live's version.

An .als file is gzip-compressed XML:
  <Ableton Creator="Ableton Live 12.1.5" ...>
    <LiveSet>
      <MainTrack> (Live 12; <MasterTrack> before) ... <Mixer><Tempo><Manual Value="140"/>
      <ScaleInformation><RootNote Value="5"/><Name Value="Minor"/></ScaleInformation>   (Live 12)
      <InKey Value="true"/>                                                              (Live 12)
      ... <MidiClip> ... <ScaleInformation>..</ScaleInformation> <IsInKey Value="true"/> ...

Key, most trusted first:
  1. the set's scale, when Live's Scale mode is on (InKey),
  2. the scale most of the set's in-key MIDI clips use,
  3. the set's scale if it isn't Live's untouched default (C Major).
Anything else = no key from the set; the app falls back to estimating it from the audio.
Sets are parsed as a stream, so big sets with lots of automation stay cheap.
"""

from __future__ import annotations

import gzip
import io
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

MASTER_TAGS = ("MasterTrack", "MainTrack")

# Live's scale names -> minor (True) / major (False). Modes map to the side their third is on.
_MINOR_WORDS = ("minor", "aeolian", "dorian", "phrygian", "locrian")
_MAJOR_WORDS = ("major", "ionian", "lydian", "mixolydian")
_INDEXED = {"0": "Major", "1": "Minor"}   # Live 11 stored some scale names as numbers


class AlsError(ValueError):
    pass


@dataclass
class AlsInfo:
    tempo: float | None              # BPM, None if it couldn't be read
    tempo_source: str                # "project" or "unreadable"
    root: int | None = None          # key root as a pitch class (0 = C), None = no key in the set
    minor: bool = False
    scale_name: str = ""             # Live's own name, e.g. "Minor", "Dorian"
    key_source: str = ""             # "scale" (Scale mode on), "clips", "set"
    live_version: str = ""           # "12.1.5"


def scale_is_minor(name: str) -> bool | None:
    n = _INDEXED.get(name.strip(), name).lower()
    if any(w in n for w in _MINOR_WORDS):
        return True
    if any(w in n for w in _MAJOR_WORDS):
        return False
    return None  # pentatonic, whole tone, ... - not a plain major/minor key


def _open(path: Path):
    raw = path.read_bytes()
    if raw[:2] == b"\x1f\x8b":
        try:
            raw = gzip.decompress(raw)
        except (OSError, EOFError) as e:  # truncated = Live is still writing it
            raise AlsError(f"incomplete set file ({e})") from e
    if raw.lstrip(b"\xef\xbb\xbf \t\r\n")[:5] not in (b"<?xml", b"<Able"):
        raise AlsError("not an Ableton Live set")
    return io.BytesIO(raw)


def _bool(v) -> bool:
    return str(v).strip().lower() == "true"


def read_als(path: str | Path) -> AlsInfo:
    path = Path(path)
    stack: list[str] = []
    tempo = None
    version = ""
    seen_root = False
    set_scale: dict = {}
    set_in_key = False
    clip: dict | None = None
    clip_scales: Counter = Counter()
    try:
        for ev, el in ET.iterparse(_open(path), events=("start", "end")):
            if ev == "start":
                stack.append(el.tag)
                if el.tag == "Ableton" and not seen_root:
                    seen_root = True
                    creator = el.get("Creator", "")
                    version = creator.replace("Ableton Live", "").strip().split(" ")[0]
                elif el.tag == "MidiClip":
                    clip = {}
                continue
            tag = el.tag
            parent = stack[-2] if len(stack) > 1 else ""
            owner = stack[-3] if len(stack) > 2 else ""
            val = el.get("Value")
            if tag == "Manual" and parent == "Tempo" and tempo is None and any(t in MASTER_TAGS for t in stack):
                try:
                    tempo = float(val)
                except (TypeError, ValueError):
                    pass
            elif parent == "ScaleInformation" and tag in ("RootNote", "Name") and val is not None:
                if owner == "LiveSet":
                    set_scale[tag] = val
                elif owner == "MidiClip" and clip is not None:
                    clip[tag] = val
            elif tag in ("InKey", "IsInKey") and val is not None:
                if parent == "LiveSet":
                    set_in_key = _bool(val)
                elif parent == "MidiClip" and clip is not None:
                    clip["in_key"] = _bool(val)
            elif tag == "MidiClip" and clip is not None:
                if clip.get("in_key") and "RootNote" in clip and "Name" in clip:
                    clip_scales[(clip["RootNote"], clip["Name"])] += 1
                clip = None
            stack.pop()
            el.clear()
    except ET.ParseError as e:
        if not seen_root:
            raise AlsError(f"not an Ableton Live set ({e})") from e
        # truncated XML: keep whatever was read before the break

    if not seen_root:
        raise AlsError("not an Ableton Live set")

    info = AlsInfo(round(tempo, 3) if tempo and 10 <= tempo <= 999 else None, "", live_version=version)
    info.tempo_source = "project" if info.tempo else "unreadable"

    choice = None
    if set_in_key and "RootNote" in set_scale and "Name" in set_scale:
        choice = (set_scale["RootNote"], set_scale["Name"]), "scale"
    elif clip_scales:
        choice = clip_scales.most_common(1)[0][0], "clips"
    elif "RootNote" in set_scale and "Name" in set_scale:
        r, n = set_scale["RootNote"], _INDEXED.get(set_scale["Name"].strip(), set_scale["Name"])
        if not (r.strip() == "0" and n.strip().lower() == "major"):  # Live's untouched default
            choice = (set_scale["RootNote"], set_scale["Name"]), "set"
    if choice:
        (root, name), src = choice
        minor = scale_is_minor(name)
        try:
            pc = int(float(root)) % 12
        except ValueError:
            minor = None
        if minor is not None:
            info.root, info.minor, info.key_source = pc, minor, src
            info.scale_name = _INDEXED.get(name.strip(), name)
    return info


if __name__ == "__main__":
    import sys
    for p in sys.argv[1:]:
        print(p, read_als(p))
