"""Colour themes: FL Studio's stock look, FL theme files (.flstheme) and custom colours.

FL Studio themes don't store panel colours directly. A .flstheme file is plain text
(`Key=value` lines) holding:
  * Hue / Saturation / Lightness / Contrast - shifts applied to FL's built-in grey skin,
  * a few colours as signed 32-bit integers. `Selected` and `TextColor` keep red in the
    high byte (0xRRGGBB); `Highlight`, `Mute`, `Option`, `Step*` are Windows COLORREFs
    (0xBBGGRR). The top byte is ignored.
FL rewrites `__current.flstheme` in its user Themes folder with the live theme when it
closes, which is what "Match FL Studio" follows.

The surface maths below is an approximation fitted to screenshots. It gets close, and
the custom colour editor (with the screen eyedropper) can fine-tune anything it misses.

Ableton Live themes (.ask) are XML: `<SkinManager>` holds named colours, either as
`<Name><R Value=../><G ../><B ../><Alpha ../></Name>` (Live 10/11) or `<Name Value="#rrggbb"/>`
(Live 12). Live doesn't write its current theme to a file, so "Match Ableton" looks up
which theme name Live's Preferences.cfg mentions (rewritten when Live closes) and loads
that theme's .ask from Live's install or user Themes folders.
"""

from __future__ import annotations

import colorsys
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

# ------------------------------------------------------------ palettes ----
# FL Studio's stock theme: blue-grey panels, orange highlights, lime "selected".
FL_DEFAULT = {
    "bg": "#3f484d",          # window body (mixer / browser panels)
    "panel": "#535c61",       # title bars, toolbar
    "field": "#2f383d",       # entry boxes, buttons (FL's dark display boxes)
    "field_hi": "#3a454b",    # hovered field
    "deep": "#252d32",        # sunken areas (playlist ruler)
    "border": "#2a3237",
    "accent": "#f7a13d",      # FL orange
    "accent_hot": "#ffb866",
    "accent_dim": "#93a5ae",  # section labels (FL's blue-grey captions)
    "btn_text": "#d3dde2",    # text on plain buttons / chips
    "on_accent": "#22292d",   # text on an orange button
    "text": "#e8eef1",
    "muted": "#8b989f",
    "warn": "#ff7a66",
    "ok": "#a8e54a",          # FL's lime "selected" colour
}

# The colours a user (or a theme file) chooses; everything else is worked out from them.
SEEDS = ("bg", "panel", "field", "accent", "text")
SEED_LABELS = {"bg": "Background", "panel": "Title bars", "field": "Boxes + buttons",
               "accent": "Accent", "text": "Text"}

MODES = ("auto", "default", "file", "custom")
CURRENT_NAME = "__current.flstheme"


# -------------------------------------------------------------- colour ----
def to_rgb(hx: str) -> tuple[int, int, int]:
    hx = hx.strip().lstrip("#")
    if len(hx) == 3:
        hx = "".join(ch * 2 for ch in hx)
    if len(hx) != 6:
        raise ValueError(f"not a colour: #{hx}")
    return int(hx[0:2], 16), int(hx[2:4], 16), int(hx[4:6], 16)


def to_hex(rgb) -> str:
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(round(v)))) for v in rgb)


def is_hex(s: str) -> bool:
    try:
        to_rgb(s)
        return True
    except (ValueError, AttributeError):
        return False


def mix(a: str, b: str, t: float) -> str:
    """t=0 -> a, t=1 -> b."""
    ra, rb = to_rgb(a), to_rgb(b)
    return to_hex(x + (y - x) * t for x, y in zip(ra, rb))


def luminance(hx: str) -> float:
    def ch(v):
        v /= 255
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = to_rgb(hx)
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def contrast(a: str, b: str) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def hue_of(hx: str) -> float:
    r, g, b = (v / 255 for v in to_rgb(hx))
    return colorsys.rgb_to_hls(r, g, b)[0] * 360


def readable(fg: str, bg: str, min_ratio: float = 3.0) -> str:
    """Push fg towards white or black until it reads on bg."""
    if contrast(fg, bg) >= min_ratio:
        return fg
    target = "#ffffff" if luminance(bg) < 0.25 else "#000000"
    for i in range(1, 11):
        c = mix(fg, target, i / 10)
        if contrast(c, bg) >= min_ratio:
            return c
    return target


def derive(seeds: dict, extra: dict | None = None) -> dict:
    """Full palette from the five seed colours (missing seeds come from FL_DEFAULT)."""
    s = {k: seeds.get(k) if is_hex(seeds.get(k) or "") else FL_DEFAULT[k] for k in SEEDS}
    s = {k: to_hex(to_rgb(v)) for k, v in s.items()}
    bg, panel, field, accent, text = s["bg"], s["panel"], s["field"], s["accent"], s["text"]
    dark = luminance(bg) < 0.35
    shade = "#000000" if dark else "#ffffff"
    lift = "#ffffff" if dark else "#000000"
    text = readable(text, bg, 4.5)
    accent = readable(accent, bg, 2.2)
    a_h = hue_of(accent)
    # warning colour: coral, unless the accent is already red-ish - then amber
    warn = "#ffc46b" if (a_h < 25 or a_h > 330) else "#ff7a66"
    if not dark:
        warn = "#b0451f" if warn == "#ff7a66" else "#9a5a00"
    pal = {
        "bg": bg, "panel": panel, "field": field,
        "field_hi": mix(field, lift, 0.08),
        "deep": mix(field, shade, 0.25),
        "border": mix(bg, shade, 0.3),
        "accent": accent,
        "accent_hot": mix(accent, lift, 0.25),
        "accent_dim": readable(mix(text, bg, 0.38), bg, 3.0),
        "btn_text": readable(mix(text, field, 0.12), field, 4.5),
        "on_accent": "#ffffff" if contrast("#ffffff", accent) >= contrast(mix(bg, "#000000", 0.5), accent)
        else mix(bg, "#000000", 0.5),
        "text": text,
        "muted": readable(mix(text, bg, 0.45), bg, 3.0),
        "warn": readable(warn, bg, 3.0),
        "ok": FL_DEFAULT["ok"],
    }
    if extra:
        pal.update({k: v for k, v in extra.items() if k in pal and is_hex(v)})
    return pal


def seeds_of(palette: dict) -> dict:
    return {k: palette[k] for k in SEEDS}


# --------------------------------------------------------- .flstheme ----
def _rgb_value(v: int) -> str:            # Selected, TextColor: 0x..RRGGBB
    u = v & 0xFFFFFF
    return to_hex(((u >> 16) & 255, (u >> 8) & 255, u & 255))


def _colorref(v: int) -> str:             # Highlight, Mute, Option, Step*: 0x..BBGGRR
    u = v & 0xFFFFFF
    return to_hex((u & 255, (u >> 8) & 255, (u >> 16) & 255))


RGB_KEYS = ("selected", "textcolor")
COLORREF_KEYS = ("highlight", "mute", "option", "stepeven", "stepodd")


def parse_flstheme(text: str) -> dict:
    """{'hue': .., 'saturation': .., 'lightness': .., 'contrast': .., 'selected': '#rrggbb', ...}.
    Unknown keys and junk lines are ignored."""
    raw = {}
    for line in text.lstrip("﻿").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            raw[k.strip().lower()] = v.strip()
    out: dict = {}
    for k in ("hue", "saturation", "lightness", "contrast"):
        try:
            out[k] = float(raw.get(k, 0))
        except ValueError:
            out[k] = 0.0
    for k in RGB_KEYS + COLORREF_KEYS:
        try:
            v = int(raw[k])
        except (KeyError, ValueError):
            continue
        out[k] = _rgb_value(v) if k in RGB_KEYS else _colorref(v)
    if not any(k in raw for k in ("hue", "saturation", "lightness", "selected", "highlight", "textcolor")):
        raise ValueError("doesn't look like an FL Studio theme")
    return out


def read_flstheme(path) -> dict:
    data = Path(path).read_bytes()
    for enc in ("utf-8-sig", "utf-16", "cp1252"):
        try:
            return parse_flstheme(data.decode(enc))
        except (UnicodeDecodeError, ValueError):
            continue
    raise ValueError("doesn't look like an FL Studio theme")


def adjust(hx: str, hue=0.0, saturation=0.0, lightness=0.0, contrast_=0.0) -> str:
    """Approximate FL's surface adjustment of one colour of its stock skin."""
    r, g, b = (v / 255 for v in to_rgb(hx))
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    h = ((h * 360 - hue) % 360) / 360
    sg = max(-1.0, min(1.0, saturation / 256))
    s = max(0.0, min(1.0, s * (1 + sg)))
    t = max(-1.0, min(1.0, lightness / 255))
    l = l * (1 - 0.885 * -t) if t < 0 else l + (1 - l) * 0.888 * t
    c = max(-1.0, min(1.0, contrast_ / 100))
    l = max(0.0, min(1.0, 0.5 + (l - 0.5) * (1 + c)))
    return to_hex(v * 255 for v in colorsys.hls_to_rgb(h, l, s))


def _chroma(hx: str) -> float:
    rgb = to_rgb(hx)
    return (max(rgb) - min(rgb)) / 255


def pick_accent(th: dict) -> str:
    """FL's Highlight colour (the orange toolbar buttons in the stock theme), unless it's
    near-grey - then the Selected colour, which is the theme's signature instead."""
    hi, sel = th.get("highlight"), th.get("selected")
    if hi and (_chroma(hi) >= 0.25 or not sel):
        return hi
    return sel or hi or FL_DEFAULT["accent"]


def palette_from_flstheme(th: dict) -> dict:
    adj = dict(hue=th.get("hue", 0), saturation=th.get("saturation", 0),
               lightness=th.get("lightness", 0), contrast_=th.get("contrast", 0))
    surf = {k: adjust(FL_DEFAULT[k], **adj) for k in ("bg", "panel", "field", "field_hi", "deep", "border")}
    seeds = dict(surf)
    seeds["accent"] = pick_accent(th)
    seeds["text"] = th.get("textcolor") or FL_DEFAULT["text"]
    pal = derive(seeds)
    # keep the adjusted stock surfaces rather than the derived approximations
    pal.update({k: surf[k] for k in ("field_hi", "deep", "border")})
    if th.get("selected"):
        pal["ok"] = th["selected"]
    if all(not adj[k] for k in adj) and not any(k in th for k in RGB_KEYS + COLORREF_KEYS):
        return dict(FL_DEFAULT)
    return pal


# ----------------------------------------------------- finding FL's theme ----
def documents_dir() -> Path:
    """The real Documents folder (follows OneDrive / moved folders on Windows)."""
    if sys.platform.startswith("win"):
        try:
            import ctypes
            buf = ctypes.create_unicode_buffer(260)
            if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf) == 0 and buf.value:  # CSIDL_PERSONAL
                return Path(buf.value)
        except Exception:
            pass
    return Path.home() / "Documents"


def theme_dirs() -> list[Path]:
    """FL's user Themes folders that exist, most likely first."""
    cands = [documents_dir(), Path.home() / "Documents", Path.home() / "OneDrive" / "Documents"]
    od = os.environ.get("OneDrive")
    if od:
        cands.append(Path(od) / "Documents")
    out = []
    for d in cands:
        p = d / "Image-Line" / "FL Studio" / "Settings" / "Themes"
        if p.is_dir() and p not in out:
            out.append(p)
    return out


def find_current_theme() -> Path | None:
    for d in theme_dirs():
        p = d / CURRENT_NAME
        if p.is_file():
            return p
    return None


# --------------------------------------------------------- Ableton Live ----
# Live 12's stock "Default Dark Neutral Medium" look: neutral greys, Live's orange.
ABLETON_SEEDS = {"bg": "#363636", "panel": "#2a2a2a", "field": "#1e1e1e", "accent": "#ffad56", "text": "#dcdcdc"}
ABLETON_DEFAULT = derive(ABLETON_SEEDS, {"ok": "#03c3d5"})

DEFAULTS = {"fl": FL_DEFAULT, "ableton": ABLETON_DEFAULT}
DEFAULT_NAMES = {"fl": "FL default", "ableton": "Ableton default"}

# .ask colour names for each seed, best match first.
ASK_SEEDS = {
    "bg": ("SurfaceBackground", "DetailViewBackground", "SurfaceArea"),
    "panel": ("SurfaceHighlight", "SurfaceArea", "Desktop"),
    "field": ("ControlBackground", "DisplayBackground", "Desktop"),
    "accent": ("ChosenDefault", "ControlOnForeground", "Progress"),
    "text": ("ControlForeground", "TextDisp"),
}


def parse_ask(text: str) -> dict:
    """{'SurfaceBackground': '#rrggbb', ...} from an Ableton .ask theme (both formats)."""
    try:
        root = ET.fromstring(text.lstrip("\ufeff").encode("utf-8"))
    except ET.ParseError as e:
        raise ValueError(f"doesn't look like an Ableton theme ({e})") from e
    sm = root if root.tag == "SkinManager" else root.find(".//SkinManager")
    if sm is None:
        raise ValueError("doesn't look like an Ableton theme")
    out: dict = {}
    for el in sm.iter():
        if el is sm or el.tag in out:
            continue
        v = (el.get("Value") or "").strip()
        if v.startswith("#") and len(v) in (7, 9) and is_hex(v[:7]):
            out[el.tag] = v[:7].lower()
            continue
        chans = [el.find(c) for c in "RGB"]
        if all(c is not None for c in chans):
            try:
                out[el.tag] = to_hex(int(float(c.get("Value"))) for c in chans)
            except (TypeError, ValueError):
                pass
    if not out:
        raise ValueError("doesn't look like an Ableton theme")
    return out


def read_ask(path) -> dict:
    data = Path(path).read_bytes()
    for enc in ("utf-8-sig", "utf-16", "cp1252"):
        try:
            return parse_ask(data.decode(enc))
        except (UnicodeDecodeError, ValueError):
            continue
    raise ValueError("doesn't look like an Ableton theme")


def palette_from_ask(colors: dict) -> dict:
    seeds = {}
    for seed, names in ASK_SEEDS.items():
        seeds[seed] = next((colors[n] for n in names if n in colors), ABLETON_SEEDS[seed])
    if seeds["panel"] == seeds["bg"]:  # Live themes often share one surface colour
        lift = "#ffffff" if luminance(seeds["bg"]) < 0.35 else "#000000"
        seeds["panel"] = mix(seeds["bg"], lift, 0.07)
    extra = {"ok": colors["SelectionFrame"]} if "SelectionFrame" in colors else {"ok": ABLETON_DEFAULT["ok"]}
    return derive(seeds, extra)


def _globs(base: Path, pattern: str) -> list[Path]:
    try:
        return sorted(base.glob(pattern)) if base.is_dir() else []
    except OSError:
        return []


def ableton_pref_files() -> list[Path]:
    """Live's Preferences.cfg files, newest first."""
    found = []
    appdata = os.environ.get("APPDATA")
    if appdata:
        found += _globs(Path(appdata) / "Ableton", "Live */Preferences/Preferences.cfg")
    found += _globs(Path.home() / "Library" / "Preferences" / "Ableton", "Live */Preferences.cfg")

    def mt(p):
        try:
            return p.stat().st_mtime
        except OSError:
            return 0
    return sorted(set(found), key=mt, reverse=True)


def ableton_theme_dirs() -> list[Path]:
    """Folders holding Live's built-in and user .ask themes."""
    out: list[Path] = []
    for env in ("ProgramData", "ProgramFiles", "ProgramW6432"):
        if os.environ.get(env):
            out += _globs(Path(os.environ[env]) / "Ableton", "*/Resources/Themes")
    out += _globs(Path("/Applications"), "Ableton Live*.app/Contents/App-Resources/Themes")
    appdata = os.environ.get("APPDATA")
    if appdata:
        out += _globs(Path(appdata) / "Ableton", "Live */Themes")
    out += _globs(Path.home() / "Library" / "Preferences" / "Ableton", "Live */Themes")
    for docs in (documents_dir(), Path.home() / "Music"):
        out += _globs(docs / "Ableton" / "User Library", "Themes")
    return list(dict.fromkeys(out))


def find_ableton_theme() -> tuple[Path | None, Path | None]:
    """(the .ask Live is using, the Preferences.cfg it was read from). Either can be None."""
    prefs = ableton_pref_files()
    if not prefs:
        return None, None
    pref = prefs[0]
    asks = [p for d in ableton_theme_dirs() for p in _globs(d, "*.ask")]
    try:
        data = pref.read_bytes()
    except OSError:
        return None, pref
    best = None
    for p in asks:
        name = p.stem
        if name.encode("utf-16-le") in data or name.encode("utf-8") in data:
            if best is None or len(name) > len(best.stem):
                best = p
    return best, pref


def auto_source(daw: str = "fl") -> Path | None:
    """The file that changes when the DAW's current theme changes."""
    if daw == "ableton":
        return find_ableton_theme()[1]
    return find_current_theme()


def _resolve_ableton(cfg: dict) -> tuple[dict, str, Path | None]:
    mode = cfg.get("theme", "auto")
    if mode == "custom":
        return derive(cfg.get("theme_colors") or {}, {"ok": ABLETON_DEFAULT["ok"]}), "your own colours", None
    if mode == "default":
        return dict(ABLETON_DEFAULT), "Ableton Live's stock look", None
    if mode == "file":
        if not cfg.get("theme_file"):
            return dict(ABLETON_DEFAULT), "no theme file chosen yet - using Ableton default", None
        p = Path(cfg["theme_file"])
        try:
            return palette_from_ask(read_ask(p)), f"from {p.name}", p
        except Exception as e:
            return dict(ABLETON_DEFAULT), f"couldn't read {p.name} ({type(e).__name__}) - using Ableton default", p
    ask, pref = find_ableton_theme()
    if not pref:
        return dict(ABLETON_DEFAULT), "Ableton Live's settings not found - using Ableton default", None
    if not ask:
        return (dict(ABLETON_DEFAULT), "couldn't tell which theme Live uses - using Ableton default "
                "(load its .ask file instead)", pref)
    try:
        return palette_from_ask(read_ask(ask)), f"synced with Ableton ({ask.stem}, updates when Live closes)", pref
    except Exception as e:
        return dict(ABLETON_DEFAULT), f"couldn't read {ask.name} ({type(e).__name__}) - using Ableton default", pref


# ------------------------------------------------------------ resolving ----
def resolve(cfg: dict) -> tuple[dict, str, Path | None]:
    """(palette, one-line status for Settings, file to watch for changes or None).
    cfg["daw"] = "ableton" resolves an Ableton theme; anything else is FL Studio."""
    if cfg.get("daw") == "ableton":
        return _resolve_ableton(cfg)
    mode = cfg.get("theme", "auto")
    if mode == "custom":
        return derive(cfg.get("theme_colors") or {}), "your own colours", None
    if mode == "default":
        return dict(FL_DEFAULT), "FL Studio's stock look", None
    if mode == "file":
        p = Path(cfg.get("theme_file") or "")
        if not cfg.get("theme_file"):
            return dict(FL_DEFAULT), "no theme file chosen yet - using FL default", None
        try:
            return palette_from_flstheme(read_flstheme(p)), f"from {p.name}", p
        except Exception as e:
            return dict(FL_DEFAULT), f"couldn't read {p.name} ({type(e).__name__}) - using FL default", p
    # auto
    p = find_current_theme()
    if not p:
        return dict(FL_DEFAULT), "FL's current theme not found - using FL default", None
    try:
        return palette_from_flstheme(read_flstheme(p)), "synced with FL Studio (updates when FL closes)", p
    except Exception as e:
        return dict(FL_DEFAULT), f"couldn't read FL's theme ({type(e).__name__}) - using FL default", p


def colorref(hx: str) -> int:
    """#rrggbb -> 0x00BBGGRR for Windows APIs."""
    r, g, b = to_rgb(hx)
    return (b << 16) | (g << 8) | r
