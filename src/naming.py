"""File-name templates, versioning and project-name cleanup."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

TOKENS = ("name", "bpm", "key", "type", "version", "typeversion", "date")
ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_TOKEN_RE = re.compile(r"\{(name|bpm|key|type|version|typeversion|date)\}")

# Export types picked in the popup. {version} counts every export of a beat; {typeversion}
# counts that beat's exports of the chosen type (8th export, 1st Master -> Master_v8_01).
TYPES = ("Stem", "Demo", "Mix", "Master")
DEFAULT_TEMPLATE = "{name}_{bpm}bpm_{key}_{type}_v{version}_{typeversion}"
# Earlier default formats: versions in files named this way are still counted.
LEGACY_TEMPLATES = ("{name}_{bpm}bpm_{key}_v{version}", "{name}_{bpm}bpm_{key}_v{version}_{type}")


def sanitize(s: str) -> str:
    s = ILLEGAL.sub("", s).replace("♭", "b").replace("♯", "#")
    s = re.sub(r"\s+", " ", s).strip(" .")
    return s


def fmt_bpm(bpm) -> str:
    if bpm in (None, ""):
        return ""
    try:
        v = float(bpm)
    except (TypeError, ValueError):
        return sanitize(str(bpm))
    return str(int(v)) if abs(v - round(v)) < 1e-6 else f"{v:.3f}".rstrip("0").rstrip(".")


def fmt_version(v, digits: int = 2) -> str:
    try:
        return str(int(v)).zfill(digits)
    except (TypeError, ValueError):
        return sanitize(str(v))


def build_stem(template: str, name: str, bpm, key: str, version, digits: int = 2,
               type_: str = "", typeversion=None, type_digits: int = 2) -> str:
    """No type = {type} and {typeversion} are left out, with their separators."""
    type_ = sanitize(type_ or "")
    vals = {
        "name": sanitize(name) or "Untitled",
        "bpm": fmt_bpm(bpm),
        "key": sanitize(key),
        "type": type_,
        "version": fmt_version(version, digits),
        "typeversion": fmt_version(typeversion, type_digits) if type_ and typeversion not in (None, "") else "",
        "date": date.today().strftime("%Y-%m-%d"),
    }
    t = template
    # Drop empty fields together with the separator in front of them
    # (no key -> "Beat_140bpm_v01", not "Beat_140bpm__v01").
    for tok, v in vals.items():
        if not v:
            tail = r"\s?bpm" if tok == "bpm" else ""
            t = re.sub(r"[ _\-]*\{" + tok + r"\}" + tail, "", t, flags=re.I)
    out = _TOKEN_RE.sub(lambda m: vals[m.group(1)], t)
    return sanitize(out.strip(" _-."))


def template_regex(template: str, name: str | None = None) -> re.Pattern:
    """Regex that parses a stem written with `template` (optionally for a fixed name)."""
    parts, pos = [], 0
    for m in _TOKEN_RE.finditer(template):
        parts.append(re.escape(template[pos:m.start()]))
        tok = m.group(1)
        if tok == "name":
            parts.append(re.escape(sanitize(name)) if name is not None else r"(?P<name>.+?)")
        elif tok == "bpm":
            parts.append(r"(?P<bpm>\d{2,3}(?:\.\d+)?)?")
        elif tok == "key":
            parts.append(r"(?P<key>[A-G](?:#|b)?(?:m|min|maj| minor| major)?)?")
        elif tok == "type":
            parts.append(r"(?P<type>" + "|".join(TYPES) + r")?")
        elif tok == "version":
            parts.append(r"(?P<version>\d+)")
        elif tok == "typeversion":
            parts.append(r"(?P<typeversion>\d+)?")
        elif tok == "date":
            parts.append(r"\d{4}-\d{2}-\d{2}")
        pos = m.end()
    parts.append(re.escape(template[pos:]))
    rx = "".join(parts)
    # Let separators be optional where a field was empty.
    rx = rx.replace(r"_", r"_?").replace(r"\ ", r"\ ?").replace(r"\-", r"\-?")
    return re.compile(rf"^{rx}(?:\s*\(\d+\))?$", re.IGNORECASE)


def parse_stem(template: str, stem: str) -> dict | None:
    m = template_regex(template).match(stem)
    if not m:
        return None
    d = {k: v for k, v in m.groupdict().items() if v}
    return d if d.get("name") else None


_SUFFIX_JUNK = [
    re.compile(r"\s*\((?:autosave|autosaved|overwritten[^)]*|backup[^)]*)\)\s*$", re.I),
    re.compile(r"[ _\-]+v\d{1,3}$", re.I),                          # _v3
    re.compile(r"[ _]\d{1,2}$"),                                     # FL "save new version" _2
    re.compile(r"[ _\-]*\d{2,3}(?:\.\d+)?\s?bpm(?=$|[ _\-])", re.I),  # 140bpm
    re.compile(r"[ _\-]*\bmaster(ed)?$", re.I),
]


_GENERIC = re.compile(r"^(project|untitled|new project|unnamed|new)(?:[ _\-]*\d+)?$", re.I)


def is_generic(name: str) -> bool:
    """FL's auto names (Project_23, Untitled 4...) - not a real beat name."""
    return bool(_GENERIC.match(name.strip()))


def clean_project_name(stem: str) -> str:
    if is_generic(stem):  # keep "Project_23" whole - stripping it to "Project" would merge every unnamed beat
        return stem.strip()
    s = stem
    for _ in range(3):
        before = s
        for rx in _SUFFIX_JUNK:
            s = rx.sub("", s).strip(" _-")
            if is_generic(s):  # stop at "Project_23" - one more strip would leave bare "Project"
                return s
        if s == before:
            break
    return s or stem


def next_versions(folder: Path, template: str, name: str, type_: str = "") -> tuple[int, int]:
    """(next overall version, next version of `type_`) for beat `name`, from the files in folder
    (and its subfolders one deep). Names in the earlier default formats count too."""
    if not folder.exists():
        return 1, 1
    rxs = [template_regex(t, name) for t in dict.fromkeys((template,) + LEGACY_TEMPLATES)]
    best = best_type = 0
    candidates = list(folder.iterdir())
    for sub in [p for p in candidates if p.is_dir()]:
        try:
            candidates += list(sub.iterdir())
        except OSError:
            pass
    for p in candidates:
        stem = p.stem if p.is_file() else p.name.removesuffix("_stems").removesuffix(" stems")
        for rx in rxs:
            m = rx.match(stem)
            if not (m and m.groupdict().get("version")):
                continue
            best = max(best, int(m.group("version")))
            g = m.groupdict()
            if type_ and (g.get("type") or "").lower() == type_.lower():
                best_type = max(best_type, int(g.get("typeversion") or 1))
            break
    return best + 1, best_type + 1


def next_version(folder: Path, template: str, name: str, digits: int = 2) -> int:
    """Highest existing version for `name` in folder (and its subfolders one deep) + 1."""
    return next_versions(folder, template, name)[0]


def unique_path(p: Path) -> Path:
    if not p.exists():
        return p
    i = 2
    while True:
        cand = p.with_name(f"{p.stem} ({i}){p.suffix}")
        if not cand.exists():
            return cand
        i += 1


def common_prefix(stems: list[str]) -> str:
    if not stems:
        return ""
    s1, s2 = min(stems), max(stems)
    i = 0
    while i < min(len(s1), len(s2)) and s1[i] == s2[i]:
        i += 1
    return s1[:i].rstrip(" _-")


# ---- hints from arbitrary old file names (Beat Sorter) ----------------------
_BPM_HINT = re.compile(r"(?<![\d.])(\d{2,3}(?:\.\d)?)\s?bpm(?![a-z])", re.I)
_KEY_HINT = re.compile(
    r"(?<![A-Za-z#])([A-G])([#b♯♭]?)\s?(minor|major|min|maj|m)?(?![A-Za-z])(?!\s*type\b)")
_JUNK_WORDS = re.compile(
    r"\b(final|finished|master(?:ed)?|mixdown|mix|export(?:ed)?|bounce[ds]?|render(?:ed)?|copy|"
    r"untagged|tagged|no ?tag|wav|mp3)\b", re.I)


def _norm_key(root: str, acc: str, qual: str, style: str = "short") -> str:
    acc = {"♯": "#", "♭": "b"}.get(acc, acc)
    minor = qual.lower() in ("m", "min", "minor")
    if style == "minmaj":
        return f"{root}{acc}{'min' if minor else 'maj'}"
    return f"{root}{acc}{'m' if minor else ''}"


def parse_hints(stem: str, template: str, key_style: str = "short") -> dict:
    """Best-effort name / bpm / key from an old export's file name."""
    parsed = parse_stem(template, stem)
    if parsed:
        return parsed
    out: dict = {}
    s = stem.replace("_", " ")  # so word boundaries work on snake_case names
    m = _BPM_HINT.search(s)
    if m:
        out["bpm"] = m.group(1)
        s = s[:m.start()] + " " + s[m.end():]
    # A key needs an explicit quality (Am, C minor, F#maj) - a bare capital
    # letter is too likely to be part of the title.
    for km in _KEY_HINT.finditer(s):
        if km.group(3):
            out["key"] = _norm_key(km.group(1), km.group(2), km.group(3), key_style)
            s = s[:km.start()] + " " + s[km.end():]
            break
    s = re.sub(r"\(\d+\)|\[\d+\]", " ", s)          # "(1)" download duplicates
    s = _JUNK_WORDS.sub(" ", s)
    s = re.sub(r"[ _\-]+v\d{1,3}\b", " ", s, flags=re.I)
    s = re.sub(r"[\s_\-.]+", " ", s).strip(" _-.")
    s = clean_project_name(s) if s else s
    out["name"] = s or stem
    return out
