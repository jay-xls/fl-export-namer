"""Shared core for FL Export Namer (watcher) and Beat Sorter (drop files).

FL Export Namer - watches FL Studio and Ableton Live renders, fills in BPM / key / version,
lets you confirm in a popup styled like the program the export came from, then renames
and files the export.

Run:  pyw fl_export_namer.pyw          (normal, sits in the system tray)
      py  fl_export_namer.pyw --demo   (shows the popup with sample data)
      py  fl_export_namer.pyw --test "C:\\path\\to\\render.wav"   (treat a file as a fresh export)
"""

from __future__ import annotations

import json
import logging
import os
import queue
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import tkinter as tk  # noqa: E402
from tkinter import filedialog, font as tkfont  # noqa: E402

from als_reader import AlsInfo, read_als  # noqa: E402
from flp_reader import FlpInfo, read_flp  # noqa: E402
import naming  # noqa: E402
import theme  # noqa: E402

APP = "FL Export Namer"
__version__ = "1.4.1"
# GitHub repo releases are published to (owner/name). Used by the update check.
UPDATE_REPO = "jlnorge/fl-export-namer"
FROZEN = getattr(sys, "frozen", False)  # running from the PyInstaller build
APPDIR = Path(os.environ.get("APPDATA") or (Path.home() / ".config")) / APP
CONFIG_PATH = APPDIR / "config.json"
STATE_PATH = APPDIR / "state.json"
LOG_PATH = APPDIR / "log.txt"

AUDIO_EXTS = {".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aif", ".aiff"}
DETECTABLE = [".wav", ".flac", ".aif", ".aiff", ".ogg", ".mp3"]

# The two programs the app works with. Each has its own folders, ignore list and theme.
DAWS = ("fl", "ableton")
DAW_NAMES = {"fl": "FL Studio", "ableton": "Ableton"}
PROJECT_EXT = {"fl": ".flp", "ableton": ".als"}
PER_DAW = ("watch_folder", "beats_folder", "ignore_folders", "theme", "theme_file", "theme_colors")


def _default_watch() -> str:
    # Jay's layout if it exists, otherwise where FL Studio keeps projects by default.
    mine = Path.home() / "Music" / "FL Projects"
    return str(mine if mine.exists() else Path.home() / "Documents" / "Image-Line" / "FL Studio" / "Projects")


def _default_ableton_watch() -> str:
    # First of these that exists; Live keeps its User Library (and usually projects) in Documents\Ableton.
    cands = [Path.home() / "Music" / "Ableton Projects", Path.home() / "Music" / "Ableton",
             theme.documents_dir() / "Ableton"]
    return str(next((p for p in cands if p.exists()), cands[-1]))


DEFAULT_CONFIG = {
    "watch_folder": _default_watch(),
    "beats_folder": str(Path.home() / "Music" / "FL Export"),
    "template": "{name}_{bpm}bpm_{key}_v{version}",
    "version_digits": 2,
    "key_style": "short",        # short = Fm / F,  minmaj = Fmin / Fmaj
    "accidentals": "mixed",      # mixed = C# Eb F# Ab Bb, or "sharps" / "flats"
    "action": "move",            # move = file leaves the project folder, copy = original stays
    "subfolder_per_beat": True,
    "folder_date": True,             # beat folders named "Name DD.MM.YYYY" (date of the beat's first export)
    "folder_date_format": "%d.%m.%Y",
    "detect_key": True,
    "check_updates": True,
    "ignore_folders": ["Backup", "Recorded", "Audio", "Sliced", "Audio Logger", "Autosave", "Samples"],
    "default_daw": "fl",         # tab Settings / Beat Sorter open on: fl or ableton
    "watch_fl": True,            # watch the FL Studio folder
    "watch_ableton": Path(_default_ableton_watch()).exists(),  # watch the Ableton folder
    "ableton_watch_folder": _default_ableton_watch(),
    "ableton_beats_folder": str(Path.home() / "Music" / "Ableton Export"),
    "ableton_ignore_folders": ["Backup", "Samples", "Ableton Project Info", "User Library", "Factory Packs",
                               "Live Recordings", "Recorded", "Processed"],
    "settle_seconds": 1.5,
    "group_seconds": 3.0,
    "stale_warning_minutes": 2,
    "theme": "auto",             # auto = match FL Studio's current theme, default, file, custom
    "theme_file": "",            # .flstheme used when theme = file
    "theme_colors": {},          # seed colours used when theme = custom (see theme.SEEDS)
    "ableton_theme": "auto",     # same choices, for the Ableton side (auto = match Live's theme)
    "ableton_theme_file": "",    # .ask used when ableton_theme = file
    "ableton_theme_colors": {},
}


def daw_key(daw: str, key: str) -> str:
    """Config key holding `key` for a program: FL keeps the original names, Ableton's are prefixed."""
    return key if daw == "fl" or key not in PER_DAW else f"{daw}_{key}"


def daw_cfg(cfg: dict, daw: str) -> dict:
    """A copy of cfg as one program sees it: watch_folder, beats_folder, theme... are that
    program's, and cfg["daw"] says which one it is."""
    out = dict(cfg)
    for k in PER_DAW:
        out[k] = cfg.get(daw_key(daw, k), DEFAULT_CONFIG[daw_key(daw, k)])
    out["daw"] = daw
    return out


def watch_enabled(cfg: dict, daw: str) -> bool:
    return bool(cfg.get(f"watch_{daw}", DEFAULT_CONFIG[f"watch_{daw}"]))

# ---------------------------------------------------------------- theme ----
# Live palette. Starts as FL Studio's stock look; App.apply_theme() swaps the values in
# place (FL theme sync, a .flstheme file, or custom colours - see theme.py), so every
# module that imported C sees the change. Windows built afterwards use the new colours.
C = dict(theme.FL_DEFAULT)


def pick_font(root, prefs, size, weight="normal"):
    fams = {f.lower(): f for f in tkfont.families(root)}
    for p in prefs:
        if p.lower() in fams:
            return (fams[p.lower()], size, weight)
    return ("TkDefaultFont", size, weight)


class Fonts:
    def __init__(self, root):
        ui = ["Bahnschrift SemiCondensed", "Bahnschrift", "Segoe UI Semibold", "Segoe UI",
              "Roboto Condensed", "DejaVu Sans Condensed", "Helvetica"]
        self.title = pick_font(root, ui, 11, "bold")
        self.label = pick_font(root, ui, 9, "bold")
        self.body = pick_font(root, ui, 11)
        self.entry = pick_font(root, ui, 12)
        self.small = pick_font(root, ui, 9)
        self.preview = pick_font(root, ui, 14, "bold")
        self.button = pick_font(root, ui, 10, "bold")


# ----------------------------------------------------------- persistence ----
def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)


OLD_DEFAULT_BEATS = str(Path.home() / "Music" / "Beats")


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    saved = load_json(CONFIG_PATH, {})
    cfg.update(saved)
    # v1 defaulted to Music\Beats. If that was never used, switch to Music\FL Export.
    if saved and cfg["beats_folder"] == OLD_DEFAULT_BEATS and not Path(OLD_DEFAULT_BEATS).exists():
        cfg["beats_folder"] = DEFAULT_CONFIG["beats_folder"]
        save_json(CONFIG_PATH, cfg)
        logging.info("moved beats folder default to %s", cfg["beats_folder"])
    if "Samples" not in cfg["ignore_folders"] and saved.get("ignore_folders") == [
            "Backup", "Recorded", "Audio", "Sliced", "Audio Logger", "Autosave"]:
        cfg["ignore_folders"] = DEFAULT_CONFIG["ignore_folders"]
        save_json(CONFIG_PATH, cfg)
    return cfg


def open_path(p, make=False):
    if make:
        Path(p).mkdir(parents=True, exist_ok=True)  # e.g. Beats folder before the first save
    p = str(p)
    if not os.path.exists(p):
        raise FileNotFoundError(f"{p} doesn't exist yet")
    if sys.platform.startswith("win"):
        os.startfile(p)  # noqa
    elif sys.platform == "darwin":
        subprocess.Popen(["open", p])
    else:
        subprocess.Popen(["xdg-open", p])


# ------------------------------------------------------ launch / startup ----
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
STARTUP_LNK = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / f"{APP}.lnk"


def launch_command(sorter: bool = False) -> list[str]:
    if FROZEN:
        return [sys.executable] + (["--sorter"] if sorter else [])
    exe = Path(sys.executable)
    pyw = exe.with_name("pythonw.exe")
    return [str(pyw if pyw.exists() else exe), str(HERE / ("beat_sorter.pyw" if sorter else "fl_export_namer.pyw"))]


def startup_enabled() -> bool:
    if not sys.platform.startswith("win"):
        return False
    if STARTUP_LNK.exists():  # created by the old setup.bat
        return True
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, APP)
        return True
    except OSError:
        return False


def set_startup(on: bool):
    if not sys.platform.startswith("win"):
        return
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if on:
            winreg.SetValueEx(k, APP, 0, winreg.REG_SZ, subprocess.list2cmdline(launch_command()))
        else:
            try:
                winreg.DeleteValue(k, APP)
            except OSError:
                pass
    if not on and STARTUP_LNK.exists():
        STARTUP_LNK.unlink()


def launch_sorter(paths=()):
    try:
        subprocess.Popen(launch_command(sorter=True) + [str(p) for p in paths])
    except Exception:
        logging.exception("couldn't start Beat Sorter")


# ----------------------------------------------------------- update check ----
UPDATE_EVERY_HOURS = 20
THEME_POLL_MS = 4000


def open_url(url: str):
    import webbrowser
    if url.startswith("https://github.com/"):
        webbrowser.open(url)


def version_tuple(v: str) -> tuple:
    parts = re.findall(r"\d+", v or "")
    return tuple(int(p) for p in parts[:3])


def fetch_latest_release(timeout: float = 8.0):
    """(version, url) of the newest GitHub release, or None. Never raises."""
    if UPDATE_REPO.startswith("OWNER/"):
        return None
    import json as _json
    import urllib.request
    req = urllib.request.Request(
        f"https://api.github.com/repos/{UPDATE_REPO}/releases/latest",
        headers={"Accept": "application/vnd.github+json", "User-Agent": f"FLExportNamer/{__version__}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = _json.loads(r.read().decode("utf-8"))
    except Exception as e:
        logging.info("update check skipped: %s", e)
        return None
    tag = str(data.get("tag_name") or "")
    url = str(data.get("html_url") or f"https://github.com/{UPDATE_REPO}/releases/latest")
    return (tag.lstrip("v"), url) if tag else None


def ago(seconds: float) -> str:
    seconds = max(0, seconds)
    if seconds < 90:
        return f"{int(seconds)}s"
    if seconds < 5400:
        return f"{int(seconds // 60)}m"
    return f"{seconds / 3600:.1f}h"


# ------------------------------------------------------------------ jobs ----
@dataclass
class Job:
    files: list[Path]
    kind: str = "single"               # single (1+ formats of one render) | stems
    stem_suffixes: dict = field(default_factory=dict)
    daw: str = "fl"                    # program the export came from: fl | ableton
    project: Path | None = None        # the .flp / .als that made it
    flp_info: FlpInfo | None = None
    als_info: AlsInfo | None = None
    als_key: str = ""                  # key the Ableton set suggests (kept so a user override sticks)
    bpm_trusted: bool = False          # BPM came from the project itself
    project_key: str = ""
    name: str = ""
    name_source: str = ""
    bpm: str = ""
    bpm_source: str = ""
    key: str = ""
    key_source: str = ""
    warnings: list[str] = field(default_factory=list)
    detect_file: Path | None = None
    created: float = field(default_factory=time.time)
    context: tuple | None = None      # (LABEL, value) row shown instead of PROJECT
    detect_bpm: bool = False          # estimate BPM from audio (standalone sorter)
    standalone: bool = False


def find_project(files: list[Path], watch_root: Path, ext: str = ".flp"):
    """Locate the project (.flp / .als) that produced these renders (same folder, or up to 2 parents).
    Returns (main project file, newest save of it)."""
    folder = files[0].parent
    export_clean = naming.clean_project_name(files[0].stem).lower()
    for _ in range(3):
        flps = [p for p in folder.glob("*" + ext)]
        if flps:
            groups: dict[str, list[Path]] = {}
            for p in flps:
                groups.setdefault(naming.clean_project_name(p.stem).lower(), []).append(p)
            if export_clean in groups:
                grp = groups[export_clean]
            else:
                grp = max(groups.values(), key=lambda g: max(x.stat().st_mtime for x in g))
            mains = [p for p in grp if "(" not in p.stem] or grp
            main = max(mains, key=lambda p: p.stat().st_mtime)
            newest = max(grp, key=lambda p: p.stat().st_mtime)
            return main, newest
        if folder == watch_root or folder.parent == folder:
            break
        folder = folder.parent
    if ext == ".als":  # exported somewhere else: Live's "<Set> Project\<Set>.als" under the watch folder
        stem = naming.clean_project_name(files[0].stem)
        p = watch_root / f"{stem} Project" / f"{stem}.als"
        if p.is_file():
            return p, p
    return None, None


def project_daw_near(folder: Path, stop: Path | None = None) -> str | None:
    """'ableton' / 'fl' if an .als / .flp sits in folder or up to 2 parents, else None."""
    for _ in range(3):
        try:
            exts = {p.suffix.lower() for p in folder.iterdir() if p.is_file()}
        except OSError:
            exts = set()
        if ".als" in exts:
            return "ableton"
        if ".flp" in exts:
            return "fl"
        if folder == stop or folder.parent == folder:
            break
        folder = folder.parent
    return None


ALS_KEY_SOURCES = {"scale": "from Live's Scale setting", "clips": "from the set's clip scales",
                   "set": "from the set's scale"}


def build_job(files: list[Path], cfg: dict, state: dict) -> Job:
    """cfg as daw_cfg() returns it: cfg["daw"] says which program the export came from."""
    daw = cfg.get("daw", "fl")
    files = sorted(files, key=lambda p: (p.suffix.lower() != ".wav", p.name.lower()))
    job = Job(files=files, daw=daw)
    tmpl = cfg["template"]
    ext = PROJECT_EXT[daw]

    stems = sorted({f.stem for f in files})
    if len(stems) > 1:
        job.kind = "stems"
        prefix = naming.common_prefix(stems)
        for f in files:
            suf = f.stem[len(prefix):].strip(" _-") if prefix else f.stem
            job.stem_suffixes[str(f)] = suf or f.stem
        export_stem = prefix or files[0].stem
    else:
        export_stem = stems[0]

    main, newest = find_project(files, Path(cfg["watch_folder"]), ext)
    remembered = {}
    if main:
        job.project = main
        job.project_key = str(main.parent / naming.clean_project_name(main.stem)).lower()
        remembered = state.get("projects", {}).get(job.project_key, {})
        try:
            if daw == "ableton":
                job.als_info = read_als(newest)
            else:
                job.flp_info = read_flp(newest)
        except Exception as e:
            logging.warning("could not read %s: %s", newest, e)
        age = files[0].stat().st_mtime - newest.stat().st_mtime
        if age > cfg["stale_warning_minutes"] * 60:
            job.warnings.append(
                f"Project last saved {ago(age)} before this export - if you changed tempo since, check the BPM.")
    else:
        job.warnings.append(f"No {ext} found next to this export - BPM and key will be estimated from the audio.")

    parsed_flp = naming.parse_stem(tmpl, main.stem) if main else None
    parsed_exp = naming.parse_stem(tmpl, export_stem)
    title = (job.flp_info.title if job.flp_info else "") or ""

    # Name
    if remembered.get("name"):
        job.name, job.name_source = remembered["name"], "remembered for this project"
    elif parsed_flp:
        job.name, job.name_source = parsed_flp["name"], "from project name"
    elif title:
        job.name, job.name_source = title, "from Project Info title"
    elif main:
        job.name = naming.clean_project_name(main.stem)
        job.name_source = (f"unnamed {DAW_NAMES[daw]} project - give it a name" if naming.is_generic(job.name)
                           else "from project name")
    else:
        job.name, job.name_source = naming.clean_project_name(export_stem), "from export name"

    # BPM: the project's tempo, else the file name, else an estimate from the audio
    fi, ai = job.flp_info, job.als_info
    if fi and fi.tempo:
        job.bpm = naming.fmt_bpm(fi.tempo)
        job.bpm_trusted = fi.tempo_source in ("project", "legacy")
        job.bpm_source = {"project": "read from project", "legacy": "read from project",
                          "default": "FL default (no tempo saved in project)"}.get(fi.tempo_source, "")
    elif ai and ai.tempo:
        job.bpm, job.bpm_source, job.bpm_trusted = naming.fmt_bpm(ai.tempo), "read from Ableton set", True
    elif parsed_exp and parsed_exp.get("bpm"):
        job.bpm, job.bpm_source = parsed_exp["bpm"], "from file name"
    else:
        job.bpm_source, job.detect_bpm = "estimating from audio…", True

    # Key: Ableton's scale (unless you changed it for this project), else remembered / names.
    # The audio estimate always runs too and is offered as chips.
    if ai and ai.root is not None:
        from key_detect import key_name
        job.als_key = key_name(ai.root, ai.minor, cfg["key_style"], cfg["accidentals"])
    if job.als_key:
        mine = remembered.get("key")
        if mine and remembered.get("als_key") == job.als_key and mine != job.als_key:
            job.key, job.key_source = mine, f"your choice for this project (Live says {job.als_key})"
        else:
            plain = ai.scale_name.lower() in ("major", "minor")
            job.key = job.als_key
            job.key_source = ALS_KEY_SOURCES.get(ai.key_source, "from Ableton set") + (
                "" if plain else f" ({ai.scale_name})")
    else:
        for src, d in (("remembered for this project", remembered),
                       ("from project name", parsed_flp or {}), ("from file name", parsed_exp or {})):
            if d.get("key"):
                job.key, job.key_source = d["key"], src
                break

    if job.kind == "single":
        by_ext = {f.suffix.lower(): f for f in files}
        job.detect_file = next((by_ext[e] for e in DETECTABLE if e in by_ext), None)
    return job


def _date_rx(fmt: str) -> str:
    rx = re.escape(fmt)
    for tok, pat in (("%d", r"\d{2}"), ("%m", r"\d{2}"), ("%Y", r"\d{4}"), ("%y", r"\d{2}")):
        rx = rx.replace(re.escape(tok), pat).replace(tok, pat)
    return rx


def dest_dir(cfg, name: str, when: float | None = None) -> Path:
    """Folder a beat is filed into.

    With dated folders on, a beat's folder is "Name DD.MM.YYYY" - dated once, by
    its first export. Later versions go into that same folder (found by name,
    whatever its date), so v02 from next week doesn't start a new folder at v01.
    """
    base = Path(cfg["beats_folder"])
    clean = naming.sanitize(name or "Untitled")
    if not cfg["subfolder_per_beat"]:
        return base
    if not cfg.get("folder_date"):
        return base / clean
    fmt = cfg.get("folder_date_format") or "%d.%m.%Y"
    rx = re.compile(rf"^{re.escape(clean)}(?: {_date_rx(fmt)})?$", re.I)
    try:
        existing = sorted((p for p in base.iterdir() if p.is_dir() and rx.match(p.name)),
                          key=lambda p: p.stat().st_ctime)
    except OSError:
        existing = []
    if existing:
        return existing[0]
    stamp = datetime.fromtimestamp(when or time.time()).strftime(fmt)
    return base / f"{clean} {stamp}"


# --------------------------------------------------------------- watcher ----
class ExportWatcher:
    """Turns raw filesystem events in one program's watch folder into finished, grouped render jobs."""

    def __init__(self, app, daw: str = "fl"):
        self.app, self.daw = app, daw
        self.pending: dict[str, list] = {}   # path -> [first_seen, size, mtime, last_change]
        self.ready: dict[str, list] = {}     # folder -> [paths]
        self.ready_t: dict[str, float] = {}
        self.own_outputs: set[str] = getattr(app, "own_outputs", set())  # shared by all watchers
        self.logged_skips: set[str] = set()
        self.lock = threading.Lock()
        self.observer = None
        self.root = ""
        self.stop_evt = threading.Event()

    @property
    def cfg(self) -> dict:
        return daw_cfg(self.app.cfg, self.daw)

    def ignored(self, p: Path) -> str:
        """Empty string = handle it; otherwise the reason it's skipped."""
        cfg = self.cfg
        if p.suffix.lower() not in AUDIO_EXTS:
            return "not audio"
        if p.name.startswith(("~", ".")):
            return "temp file"
        sp = str(p).lower()
        if sp in self.own_outputs:
            return "written by Export Namer"
        for d in DAWS:
            beats = str(Path(daw_cfg(self.app.cfg, d)["beats_folder"])).lower().rstrip("\\/")
            if sp.startswith(beats + "\\") or sp.startswith(beats + "/"):
                return "already in Beats folder"
        try:
            rel = p.relative_to(cfg["watch_folder"])
        except ValueError:
            return "outside watch folder"
        # Both programs can watch overlapping folders: the most specific watch folder wins,
        # and for the same folder the project file next to the export decides.
        for other in DAWS:
            if other == self.daw or not watch_enabled(self.app.cfg, other):
                continue
            try:
                orel = p.relative_to(daw_cfg(self.app.cfg, other)["watch_folder"])
            except ValueError:
                continue
            if len(orel.parts) < len(rel.parts):
                return f"inside the {DAW_NAMES[other]} watch folder"
            if len(orel.parts) == len(rel.parts):
                owner = project_daw_near(p.parent, Path(cfg["watch_folder"])) or DAWS[0]
                if owner != self.daw:
                    return f"looks like a {DAW_NAMES[owner]} export"
        names = {x.strip().lower() for x in cfg["ignore_folders"] if x.strip()}
        hit = next((part for part in rel.parts[:-1] if part.lower() in names), None)
        if hit:
            return f"inside ignored subfolder '{hit}'"
        parent = str(p.parent).lower()
        for x in self.app.state.get("ignored_paths", []):
            x = x.lower()
            if parent == x or parent.startswith(x + os.sep):
                return "folder ignored from popup"
        return ""

    def on_path(self, path: str):
        if self.app.paused:
            return
        p = Path(path)
        why = self.ignored(p)
        if why:
            if why not in ("not audio", "written by Export Namer") and path not in self.logged_skips:
                self.logged_skips.add(path)
                logging.info("skipped %s (%s)", path, why)
            return
        with self.lock:
            if path not in self.pending:
                logging.info("seen %s", path)
                self.pending[path] = [time.time(), -1, -1, time.time()]

    def start(self):
        from watchdog.events import FileSystemEventHandler
        from watchdog.observers import Observer

        outer = self

        class H(FileSystemEventHandler):
            def on_created(self, e):
                if not e.is_directory:
                    outer.on_path(e.src_path)

            def on_moved(self, e):
                if not e.is_directory:
                    outer.on_path(e.dest_path)

            def on_modified(self, e):
                if not e.is_directory and e.src_path in outer.pending:
                    outer.on_path(e.src_path)

        root = Path(self.cfg["watch_folder"])
        root.mkdir(parents=True, exist_ok=True)
        self.stop_evt = threading.Event()
        self.observer = Observer()
        self.observer.schedule(H(), str(root), recursive=True)
        self.observer.start()
        self.root = str(root)
        threading.Thread(target=self.loop, args=(self.stop_evt,), daemon=True).start()
        logging.info("watching %s (%s)", root, DAW_NAMES[self.daw])

    def stop(self):
        self.stop_evt.set()
        if self.observer:
            self.observer.stop()
        self.observer = None

    def restart(self):
        self.stop()
        self.start()

    def loop(self, stop_evt):
        cfg = self.app.cfg
        while not stop_evt.wait(0.4):
            now = time.time()
            with self.lock:
                for path, rec in list(self.pending.items()):
                    try:
                        st = os.stat(path)
                    except OSError:
                        del self.pending[path]
                        continue
                    if (st.st_size, st.st_mtime) != (rec[1], rec[2]):
                        rec[1], rec[2], rec[3] = st.st_size, st.st_mtime, now
                        continue
                    if st.st_size > 0 and now - rec[3] >= cfg["settle_seconds"]:
                        try:
                            with open(path, "rb"):
                                pass
                        except OSError:
                            continue
                        del self.pending[path]
                        folder = str(Path(path).parent)
                        self.ready.setdefault(folder, []).append(path)
                        self.ready_t[folder] = now
                busy = {str(Path(p).parent) for p in self.pending}
                for folder in list(self.ready):
                    if folder not in busy and now - self.ready_t[folder] >= cfg["group_seconds"]:
                        files = [Path(p) for p in dict.fromkeys(self.ready.pop(folder)) if os.path.exists(p)]
                        self.ready_t.pop(folder, None)
                        if files:
                            self.app.submit_files(files, self.daw)


# ------------------------------------------------------------ ui helpers ----
class FlatButton(tk.Label):
    def __init__(self, master, text, command, fonts, primary=False, **kw):
        self.primary = primary
        self.cmd = command
        bg = C["accent"] if primary else C["field"]
        fg = C["on_accent"] if primary else C["btn_text"]
        super().__init__(master, text=text, bg=bg, fg=fg, font=fonts.button,
                         padx=16, pady=7, cursor="hand2", **kw)
        self.bind("<Enter>", lambda e: self.config(bg=C["accent_hot"] if primary else C["field_hi"]))
        self.bind("<Leave>", lambda e: self.config(bg=C["accent"] if primary else C["field"]))
        self.bind("<Button-1>", lambda e: self.cmd())


def flat_entry(master, fonts, width=10, textvariable=None):
    return tk.Entry(master, width=width, textvariable=textvariable, bg=C["field"], fg=C["text"],
                    insertbackground=C["accent"], relief="flat", font=fonts.entry,
                    highlightthickness=1, highlightbackground=C["border"], highlightcolor=C["accent"],
                    selectbackground=C["accent"], selectforeground=C["on_accent"],
                    disabledbackground=C["field"])


class Segmented(tk.Frame):
    def __init__(self, master, fonts, options, value, command=None):
        super().__init__(master, bg=C["border"], padx=1, pady=1)
        self.value, self.command = value, None
        self.labels = {}
        for i, (val, text) in enumerate(options):
            lb = tk.Label(self, text=text, font=fonts.small, padx=10, pady=4, cursor="hand2")
            lb.grid(row=0, column=i, padx=(0 if i == 0 else 1, 0))
            lb.bind("<Button-1>", lambda e, v=val: self.set(v))
            self.labels[val] = lb
        self.set(value.get())
        self.command = command

    def set(self, v):
        self.value.set(v)
        for val, lb in self.labels.items():
            on = val == v
            lb.config(bg=C["accent"] if on else C["field"], fg=C["on_accent"] if on else C["muted"])
        if self.command:
            self.command()


class Toggle(tk.Label):
    def __init__(self, master, fonts, text, var: tk.BooleanVar, command=None):
        super().__init__(master, font=fonts.small, bg=master["bg"], cursor="hand2")
        self.var, self.text, self.command = var, text, command
        self.bind("<Button-1>", self.flip)
        self.render()

    def flip(self, _=None):
        self.var.set(not self.var.get())
        self.render()
        if self.command:
            self.command()

    def render(self):
        on = self.var.get()
        self.config(text=("■  " if on else "□  ") + self.text, fg=C["accent"] if on else C["muted"])


class ThemedWindow(tk.Toplevel):
    """Borderless window with an FL-style title bar."""

    def __init__(self, app, title, width):
        super().__init__(app.root)
        self.app, self.f = app, app.fonts
        self.withdraw()
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.configure(bg=C["accent_dim"])
        self.width = width
        outer = tk.Frame(self, bg=C["bg"])
        outer.pack(fill="both", expand=True, padx=1, pady=1)

        bar = tk.Frame(outer, bg=C["panel"], height=32)
        bar.pack(fill="x")
        bar.pack_propagate(False)
        logo = tk.Canvas(bar, width=18, height=18, bg=C["panel"], highlightthickness=0)
        logo.pack(side="left", padx=(10, 6))
        for i, h in enumerate((6, 12, 16, 9, 13)):
            logo.create_rectangle(1 + i * 3.5, 17 - h, 3 + i * 3.5, 17, fill=C["accent"], width=0)
        tk.Label(bar, text=title.upper(), bg=C["panel"], fg=C["accent"], font=self.f.title).pack(side="left")
        self.badge = tk.Label(bar, text="", bg=C["panel"], fg=C["muted"], font=self.f.small)
        self.badge.pack(side="left", padx=10)
        close = tk.Label(bar, text="✕", bg=C["panel"], fg=C["muted"], font=self.f.title, padx=12, cursor="hand2")
        close.pack(side="right", fill="y")
        close.bind("<Enter>", lambda e: close.config(bg=C["accent"], fg=C["on_accent"]))
        close.bind("<Leave>", lambda e: close.config(bg=C["panel"], fg=C["muted"]))
        close.bind("<Button-1>", lambda e: self.on_close())
        for w in (bar, logo):
            w.bind("<ButtonPress-1>", self._drag_start)
            w.bind("<B1-Motion>", self._drag)
        tk.Frame(outer, bg=C["border"], height=1).pack(fill="x")

        self.body = tk.Frame(outer, bg=C["bg"], padx=18, pady=14)
        self.body.pack(fill="both", expand=True)

    def _drag_start(self, e):
        self._dx, self._dy = e.x_root - self.winfo_x(), e.y_root - self.winfo_y()

    def _drag(self, e):
        self.geometry(f"+{e.x_root - self._dx}+{e.y_root - self._dy}")

    def show(self):
        self.update_idletasks()
        w = max(self.width, self.winfo_reqwidth())
        h = self.winfo_reqheight()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"{w}x{h}+{(sw - w) // 2}+{int((sh - h) * 0.4)}")
        self.deiconify()
        self.lift()
        self.after(50, self.focus_force)

    def on_close(self):
        self.destroy()


def label(master, fonts, text, fg=None, font=None, **kw):
    return tk.Label(master, text=text, bg=master["bg"], fg=fg or C["accent_dim"],
                    font=font or fonts.label, anchor="w", justify="left", **kw)


def short(s: str, n=58) -> str:
    return s if len(s) <= n else s[: n // 2 - 1] + "…" + s[-(n // 2 - 1):]


# ------------------------------------------------------------------ popup ----
ALL_KEYS = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]


class ExportPopup(ThemedWindow):
    def __init__(self, app, job: Job):
        super().__init__(app, f"{getattr(app, 'popup_title', 'Export Namer')}  ·  {DAW_NAMES[job.daw]}", 580)
        self.job = job
        self.cfg = cfg = daw_cfg(app.cfg, job.daw)  # this program's folders
        b, f = self.body, self.f
        self.user_set_version = False
        self.user_set_key = False

        # Source / project lines
        src = job.files[0].name if job.kind == "single" else f"{len(job.files)} stems"
        if job.kind == "single" and len(job.files) > 1:
            src += "  +  " + ", ".join(p.suffix.lstrip(".").upper() for p in job.files[1:])
        label(b, f, "FILE" if job.standalone else "EXPORT").grid(row=0, column=0, sticky="w")
        label(b, f, short(src), fg=C["text"], font=f.body).grid(row=0, column=1, columnspan=3, sticky="w")
        proj = "no project found"
        if job.project:
            proj = job.project.name
            if job.flp_info and job.flp_info.fl_version:
                proj += f"   ·   FL {job.flp_info.fl_version.split('.')[0]}"
            elif job.als_info and job.als_info.live_version:
                proj += f"   ·   Live {job.als_info.live_version}"
        ctx_label = "PROJECT"
        if job.context:
            ctx_label, proj = job.context
        label(b, f, ctx_label).grid(row=1, column=0, sticky="w", pady=(2, 0))
        label(b, f, short(proj), fg=C["muted"], font=f.body).grid(row=1, column=1, columnspan=3, sticky="w", pady=(2, 0))
        tk.Frame(b, bg=C["border"], height=1).grid(row=2, column=0, columnspan=4, sticky="ew", pady=12)

        # Fields
        self.v_name = tk.StringVar(value=job.name)
        self.v_bpm = tk.StringVar(value=job.bpm)
        self.v_key = tk.StringVar(value=job.key)
        self.v_ver = tk.StringVar()
        self.v_keep = tk.BooleanVar(value=app.default_keep())
        self.user_set_bpm = False

        r = 3
        label(b, f, "NAME").grid(row=r, column=0, sticky="w", padx=(0, 14))
        self.e_name = flat_entry(b, f, 34, self.v_name)
        self.e_name.grid(row=r, column=1, columnspan=3, sticky="ew", ipady=5)
        r += 1
        self.hint(r, job.name_source, warn=naming.is_generic(job.name))

        r += 1
        label(b, f, "BPM").grid(row=r, column=0, sticky="w")
        row = tk.Frame(b, bg=C["bg"])
        row.grid(row=r, column=1, columnspan=3, sticky="w")
        self.e_bpm = flat_entry(row, f, 7, self.v_bpm)
        self.e_bpm.pack(side="left", ipady=5)
        self.stepper(row, self.v_bpm, 1, mark_bpm=True)
        self.bpm_chips = tk.Frame(row, bg=C["bg"])
        self.bpm_chips.pack(side="left", padx=(10, 0))
        self.bpm_link = None
        if not job.detect_bpm and job.detect_file:  # project / file name gave a BPM - offer a second opinion
            self.bpm_link = tk.Label(row, text="check against audio", bg=C["bg"], fg=C["muted"], font=f.small,
                                     cursor="hand2")
            self.bpm_link.pack(side="left", padx=(10, 0))
            self.bpm_link.bind("<Button-1>", lambda e: self.ask_bpm_estimate())
            self.bpm_link.bind("<Enter>", lambda e: self.bpm_link.config(fg=C["accent"]))
            self.bpm_link.bind("<Leave>", lambda e: self.bpm_link.config(fg=C["muted"]))
        self.e_bpm.bind("<Key>", lambda e: setattr(self, "user_set_bpm", True))
        r += 1
        if job.standalone or job.detect_bpm:
            self.bpm_hint = self.hint(r, job.bpm_source or "estimating from audio…")
        else:
            self.bpm_hint = self.hint(r, job.bpm_source, warn=not job.bpm_trusted)

        r += 1
        label(b, f, "KEY").grid(row=r, column=0, sticky="w")
        row = tk.Frame(b, bg=C["bg"])
        row.grid(row=r, column=1, columnspan=3, sticky="w")
        self.e_key = flat_entry(row, f, 7, self.v_key)
        self.e_key.pack(side="left", ipady=5)
        drop = tk.Label(row, text="▾", bg=C["field"], fg=C["btn_text"], font=f.body, padx=8, pady=4, cursor="hand2")
        drop.pack(side="left", padx=(2, 10), fill="y")
        drop.bind("<Button-1>", lambda e: self.key_menu(drop))
        self.chips = tk.Frame(row, bg=C["bg"])
        self.chips.pack(side="left")
        r += 1
        self.key_hint = self.hint(r, job.key_source or ("detecting from audio…" if job.detect_file and cfg["detect_key"]
                                                        else "type it in"))
        self.e_key.bind("<Key>", lambda e: setattr(self, "user_set_key", True))

        r += 1
        label(b, f, "VERSION").grid(row=r, column=0, sticky="w")
        row = tk.Frame(b, bg=C["bg"])
        row.grid(row=r, column=1, columnspan=3, sticky="w")
        self.e_ver = flat_entry(row, f, 5, self.v_ver)
        self.e_ver.pack(side="left", ipady=5)
        self.e_ver.bind("<Key>", lambda e: setattr(self, "user_set_version", True))
        self.stepper(row, self.v_ver, 1, mark_user=True)
        r += 1
        self.ver_hint = self.hint(r, "")

        # Preview
        r += 1
        pv = tk.Frame(b, bg=C["deep"], highlightthickness=1, highlightbackground=C["border"], padx=14, pady=10)
        pv.grid(row=r, column=0, columnspan=4, sticky="ew", pady=(14, 0))
        tk.Label(pv, text="SAVES AS", bg=C["deep"], fg=C["accent_dim"], font=f.label).pack(anchor="w")
        self.p_name = tk.Label(pv, text="", bg=C["deep"], fg=C["accent"], font=f.preview, anchor="w", justify="left",
                               wraplength=520)
        self.p_name.pack(anchor="w", pady=(2, 0))
        self.p_dir = tk.Label(pv, text="", bg=C["deep"], fg=C["muted"], font=f.small, anchor="w", justify="left",
                              wraplength=520)
        self.p_dir.pack(anchor="w")
        self.p_warn = tk.Label(pv, text="", bg=C["deep"], fg=C["warn"], font=f.small, anchor="w", justify="left",
                               wraplength=520)

        if job.warnings:
            r += 1
            tk.Label(b, text="⚠  " + "\n⚠  ".join(job.warnings), bg=C["bg"], fg=C["warn"], font=f.small,
                     justify="left", anchor="w", wraplength=540).grid(row=r, column=0, columnspan=4, sticky="w",
                                                                      pady=(10, 0))

        # Bottom row
        r += 1
        bot = tk.Frame(b, bg=C["bg"])
        bot.grid(row=r, column=0, columnspan=4, sticky="ew", pady=(16, 0))
        Toggle(bot, f, "Keep original file" if job.standalone else "Keep original in project folder",
               self.v_keep, self.refresh).pack(side="left")
        if not job.standalone:
            ign = tk.Label(bot, text="ignore this folder", bg=C["bg"], fg=C["muted"], font=f.small, cursor="hand2")
            ign.pack(side="left", padx=(16, 0))
            ign.bind("<Button-1>", lambda e: self.ignore_folder())
        FlatButton(bot, "SAVE  ⏎", self.save, f, primary=True).pack(side="right")
        FlatButton(bot, "SKIP", self.on_close, f).pack(side="right", padx=(0, 8))

        b.columnconfigure(3, weight=1)
        for v in (self.v_name, self.v_bpm, self.v_key, self.v_ver, self.v_keep):
            v.trace_add("write", lambda *a: self.refresh())
        self.v_name.trace_add("write", lambda *a: self.suggest_version())
        self.bind("<Return>", lambda e: self.save())
        self.bind("<Escape>", lambda e: self.on_close())

        self.suggest_version()
        self.refresh()
        self.show()
        if naming.is_generic(job.name):  # Project_23 -> just start typing to replace it
            self.after(80, lambda: (self.e_name.focus_set(), self.e_name.select_range(0, "end")))
        else:
            self.after(80, lambda: (self.e_name.focus_set(), self.e_name.icursor("end")))

    # -- helpers
    def hint(self, row, text, warn=False):
        lb = tk.Label(self.body, text=text, bg=C["bg"], fg=C["warn"] if warn else C["muted"], font=self.f.small,
                      anchor="w")
        lb.grid(row=row, column=1, columnspan=3, sticky="w", pady=(1, 6))
        return lb

    def stepper(self, row, var, step, mark_user=False, mark_bpm=False):
        def bump(d):
            try:
                v = float(var.get() or 0) + d
            except ValueError:
                return
            if mark_user:
                self.user_set_version = True
            if mark_bpm:
                self.user_set_bpm = True
            var.set(naming.fmt_bpm(max(v, 1)) if var is self.v_bpm else str(int(max(v, 1))))
        for txt, d in (("−", -step), ("+", step)):
            lb = tk.Label(row, text=txt, bg=C["field"], fg=C["btn_text"], font=self.f.body, padx=9, pady=4,
                          cursor="hand2")
            lb.pack(side="left", padx=(2, 0), fill="y")
            lb.bind("<Button-1>", lambda e, d=d: bump(d))
            lb.bind("<Enter>", lambda e, w=lb: w.config(bg=C["field_hi"]))
            lb.bind("<Leave>", lambda e, w=lb: w.config(bg=C["field"]))

    def ask_bpm_estimate(self):
        if self.bpm_link is not None:
            self.bpm_link.destroy()
            self.bpm_link = None
        self.bpm_hint.config(text=f"{self.job.bpm_source} · estimating from audio…")
        self.app.estimate_bpm(self, self.job)

    def key_menu(self, anchor):
        cfg = self.cfg
        m = tk.Menu(self, tearoff=0, bg=C["panel"], fg=C["text"], activebackground=C["accent"],
                    activeforeground=C["on_accent"], font=self.f.body, bd=0)
        from key_detect import key_name
        for minor in (True, False):
            for i in range(12):
                k = key_name(i, minor, cfg["key_style"], cfg["accidentals"])
                m.add_command(label=k, command=lambda k=k: self.set_key(k), columnbreak=(i == 0 and not minor))
        m.tk_popup(anchor.winfo_rootx(), anchor.winfo_rooty() + anchor.winfo_height())

    def set_key(self, k):
        self.user_set_key = True
        self.v_key.set(k)
        self.render_chips()

    def set_detection(self, results, error=None):
        if not self.winfo_exists():
            return
        self.detected = results
        if error:
            self.key_hint.config(text=f"key detection failed ({error}) - type it in", fg=C["warn"])
        elif not results:
            self.key_hint.config(text="couldn't detect a key - type it in", fg=C["warn"])
        else:
            top, conf = results[0]
            if not self.v_key.get() and not self.user_set_key:
                self.v_key.set(top)
                self.key_hint.config(text=f"detected from audio · {'confident' if conf > .6 else 'unsure - check it'}",
                                     fg=C["muted"] if conf > .6 else C["warn"])
            elif self.job.key_source:
                self.key_hint.config(text=f"{self.job.key_source} · audio suggests {top}")
        self.render_chips()
        self.show_resize()

    def set_bpm_detection(self, results, error=None):
        if not self.winfo_exists():
            return
        self.bpm_detected = results
        if error:
            self.bpm_hint.config(text=f"tempo estimate failed ({error}) - type it in", fg=C["warn"])
        elif not results:
            self.bpm_hint.config(text="no clear beat found - type it in", fg=C["warn"])
        else:
            top, conf = results[0]
            if not self.v_bpm.get() and not self.user_set_bpm:
                self.v_bpm.set(naming.fmt_bpm(top))
                sure = conf > .6
                self.bpm_hint.config(
                    text="estimated from audio · " + ("confident" if sure else "check half/double time"),
                    fg=C["muted"] if sure else C["warn"])
            else:
                self.bpm_hint.config(text=f"{self.job.bpm_source} · audio suggests {naming.fmt_bpm(top)}")
        self.render_bpm_chips()
        self.show_resize()

    def set_bpm(self, b):
        self.user_set_bpm = True
        self.v_bpm.set(naming.fmt_bpm(b))
        self.render_bpm_chips()

    def render_bpm_chips(self):
        for w in self.bpm_chips.winfo_children():
            w.destroy()
        for b, conf in getattr(self, "bpm_detected", [])[:3]:
            on = naming.fmt_bpm(b) == self.v_bpm.get()
            c = tk.Label(self.bpm_chips, text=f"{naming.fmt_bpm(b)}  {int(round(conf * 100))}%", font=self.f.small,
                         padx=8, pady=4, bg=C["accent"] if on else C["field"],
                         fg=C["on_accent"] if on else C["btn_text"], cursor="hand2")
            c.pack(side="left", padx=(0, 4))
            c.bind("<Button-1>", lambda e, b=b: self.set_bpm(b))

    def render_chips(self):
        for w in self.chips.winfo_children():
            w.destroy()
        for k, conf in getattr(self, "detected", [])[:3]:
            on = k == self.v_key.get()
            c = tk.Label(self.chips, text=f"{k}  {int(round(conf * 100))}%", font=self.f.small, padx=8, pady=4,
                         bg=C["accent"] if on else C["field"], fg=C["on_accent"] if on else C["btn_text"],
                         cursor="hand2")
            c.pack(side="left", padx=(0, 4))
            c.bind("<Button-1>", lambda e, k=k: self.set_key(k))

    def show_resize(self):
        self.update_idletasks()
        self.geometry(f"{max(self.width, self.winfo_reqwidth())}x{self.winfo_reqheight()}")

    def suggest_version(self):
        if self.user_set_version:
            return
        cfg = self.cfg
        d = dest_dir(cfg, self.v_name.get(), self.job_date())
        nv = naming.next_version(d, cfg["template"], naming.sanitize(self.v_name.get()), cfg["version_digits"])
        self.v_ver.set(str(nv))
        self.ver_hint.config(text=(f"v{naming.fmt_version(nv - 1, cfg['version_digits'])} already in "
                                   f"{short(str(d), 46)}" if nv > 1 else "first export of this beat"))

    def job_date(self) -> float:
        try:
            return min(f.stat().st_mtime for f in self.job.files)
        except OSError:
            return time.time()

    def targets(self):
        cfg, job = self.cfg, self.job
        stem = naming.build_stem(cfg["template"], self.v_name.get(), self.v_bpm.get(), self.v_key.get(),
                                 self.v_ver.get(), cfg["version_digits"])
        d = dest_dir(cfg, self.v_name.get(), self.job_date())
        if job.kind == "stems":
            sd = d / f"{stem}_stems"
            return stem, sd, [(f, sd / f"{stem}_{naming.sanitize(job.stem_suffixes[str(f)])}{f.suffix.lower()}")
                              for f in job.files]
        return stem, d, [(f, d / f"{stem}{f.suffix.lower()}") for f in job.files]

    def refresh(self):
        if not hasattr(self, "p_name"):
            return
        stem, d, pairs = self.targets()
        exts = list(dict.fromkeys(p.suffix.lower() for p in self.job.files))
        if self.job.kind == "stems":
            self.p_name.config(text=f"{stem}_stems/")
            self.p_dir.config(text=f"{len(pairs)} stems  →  {d}")
        else:
            self.p_name.config(text=stem + exts[0] + (f"  (+{', '.join(exts[1:])})" if len(exts) > 1 else ""))
            self.p_dir.config(text=("copy to  " if self.v_keep.get() else "move to  ") + str(d))
        clash = [t for _, t in pairs if t.exists()]
        if clash:
            self.p_warn.config(text=f"{clash[0].name} already exists - will save as “… (2)”")
            self.p_warn.pack(anchor="w", pady=(4, 0))
        else:
            self.p_warn.pack_forget()

    def ignore_folder(self):
        folder = str(self.job.files[0].parent)
        st = self.app.state.setdefault("ignored_paths", [])
        if folder.lower() not in [x.lower() for x in st]:
            st.append(folder)
            save_json(STATE_PATH, self.app.state)
        self.app.toast(f"Ignoring {short(folder, 50)}")
        self.on_close()

    def save(self):
        if not self.v_name.get().strip():
            self.e_name.config(highlightbackground=C["warn"])
            return
        try:
            int(self.v_ver.get())
        except ValueError:
            self.e_ver.config(highlightbackground=C["warn"])
            return
        stem, d, pairs = self.targets()
        ok = self.app.apply(self.job, pairs, keep=self.v_keep.get(),
                            name=self.v_name.get().strip(), bpm=self.v_bpm.get().strip(),
                            key=self.v_key.get().strip(), version=int(self.v_ver.get()), folder=d)
        if ok:
            self.saved = True
            self.on_close()

    def on_close(self):
        self.destroy()
        self.app.popup_closed(self.job, getattr(self, "saved", False))


# --------------------------------------------------------------- settings ----
class SettingsWindow(ThemedWindow):
    """Settings, with a tab per program. Each tab shows that program's folders and theme, in
    that program's colours; switching tabs rebuilds the window and keeps unsaved edits."""

    def __init__(self, app, first_run=False, daw=None, draft=None, at=None, prev_daw=None):
        self.daw = daw if daw in DAWS else app.cfg.get("default_daw", "fl")
        self.prev_daw = prev_daw or app.daw
        self.draft = draft if draft is not None else json.loads(json.dumps(app.cfg))
        self.draft.setdefault("_startup", startup_enabled())
        app.apply_theme(cfg=daw_cfg(self.draft, self.daw), daw=self.daw)  # this tab's (unsaved) colours
        super().__init__(app, "Export Namer · Settings" if not first_run else "Export Namer · Setup", 600)
        self.first_run, self.at = first_run, at
        d, b, f = daw_cfg(self.draft, self.daw), self.body, self.f
        name = DAW_NAMES[self.daw]
        r = 0
        if first_run:
            label(b, f, f"Pick where {name} saves projects and where finished beats should go.\n"
                        "Use the other tab to set up the other program too.", fg=C["text"],
                  font=f.body).grid(row=r, column=0, columnspan=3, sticky="w", pady=(0, 12))
            r += 1

        # Program tabs
        label(b, f, "PROGRAM").grid(row=r, column=0, sticky="w", padx=(0, 14))
        trow = tk.Frame(b, bg=C["bg"])
        trow.grid(row=r, column=1, columnspan=2, sticky="w")
        self.v_daw = tk.StringVar(value=self.daw)
        Segmented(trow, f, [(k, DAW_NAMES[k].upper()) for k in DAWS], self.v_daw,
                  command=lambda: self.switch(self.v_daw.get())).pack(side="left")
        self.default_lbl = tk.Label(trow, text="", bg=C["bg"], font=f.small)
        self.default_lbl.pack(side="left", padx=(12, 0))
        self.default_lbl.bind("<Button-1>", lambda e: self.set_default())
        self.render_default()
        r += 1
        tk.Frame(b, bg=C["border"], height=1).grid(row=r, column=0, columnspan=3, sticky="ew", pady=10)
        r += 1

        # This program's settings
        self.v_watch = tk.StringVar(value=d["watch_folder"])
        self.v_beats = tk.StringVar(value=d["beats_folder"])
        self.v_on = tk.BooleanVar(value=watch_enabled(self.draft, self.daw))
        self.v_ign = tk.StringVar(value=", ".join(d["ignore_folders"]))
        watch_hint = ("FL projects root - all subfolders are watched" if self.daw == "fl" else
                      "where your Live projects live - all subfolders are watched")
        for lab, var, hint in (("WATCH FOLDER", self.v_watch, watch_hint),
                               ("BEATS FOLDER", self.v_beats, f"renamed {name} exports land here")):
            label(b, f, lab).grid(row=r, column=0, sticky="w", padx=(0, 14))
            e = flat_entry(b, f, 40, var)
            e.grid(row=r, column=1, sticky="ew", ipady=4)
            FlatButton(b, "BROWSE", lambda v=var: self.browse(v), f).grid(row=r, column=2, padx=(6, 0))
            label(b, f, hint, fg=C["muted"], font=f.small).grid(row=r + 1, column=1, sticky="w", pady=(1, 8))
            r += 2
        tg0 = tk.Frame(b, bg=C["bg"])
        tg0.grid(row=r, column=1, columnspan=2, sticky="w", pady=(0, 8))
        Toggle(tg0, f, f"Watch for {name} exports (both programs can be watched at once)", self.v_on).pack(side="left")
        r += 1
        label(b, f, "IGNORE").grid(row=r, column=0, sticky="w")
        flat_entry(b, f, 40, self.v_ign).grid(row=r, column=1, columnspan=2, sticky="ew", ipady=4)
        label(b, f, "subfolder names to skip (recordings, backups…)", fg=C["muted"], font=f.small).grid(
            row=r + 1, column=1, columnspan=2, sticky="w")
        r += 2

        # Theme (per program)
        self.v_theme = tk.StringVar(value=d.get("theme", "auto"))
        self.theme_file = d.get("theme_file", "")
        self.theme_colors = dict(d.get("theme_colors") or {})
        label(b, f, "THEME").grid(row=r, column=0, sticky="w", pady=(10, 4))
        self.theme_seg = Segmented(b, f, [("auto", f"Match {name}"), ("default", theme.DEFAULT_NAMES[self.daw]),
                                          ("file", "Theme file"), ("custom", "Custom")], self.v_theme,
                                   command=self.update_theme)
        self.theme_seg.grid(row=r, column=1, columnspan=2, sticky="w", pady=(10, 4))
        r += 1
        srow = tk.Frame(b, bg=C["bg"])
        srow.grid(row=r, column=1, columnspan=2, sticky="ew")
        self.swatch = tk.Canvas(srow, width=5 * 16, height=14, bg=C["bg"], highlightthickness=0)
        self.swatch.pack(side="left", padx=(0, 8))
        self.theme_status = label(srow, f, "", fg=C["muted"], font=f.small, wraplength=430)
        self.theme_status.pack(side="left")
        r += 1
        tb = tk.Frame(b, bg=C["bg"])
        tb.grid(row=r, column=1, columnspan=2, sticky="w", pady=(6, 0))
        FlatButton(tb, "LOAD .FLSTHEME…" if self.daw == "fl" else "LOAD .ASK…", self.load_theme_file,
                   f).pack(side="left")
        FlatButton(tb, "EDIT COLOURS…", self.edit_colours, f).pack(side="left", padx=(6, 0))
        r += 1

        # Shared by both programs
        dv = self.draft
        self.v_tmpl = tk.StringVar(value=dv["template"])
        self.v_style = tk.StringVar(value=dv["key_style"])
        self.v_acc = tk.StringVar(value=dv["accidentals"])
        self.v_action = tk.StringVar(value=dv["action"])
        self.v_sub = tk.BooleanVar(value=dv["subfolder_per_beat"])
        self.v_date = tk.BooleanVar(value=dv.get("folder_date", True))
        self.v_detect = tk.BooleanVar(value=dv["detect_key"])
        self.v_updates = tk.BooleanVar(value=dv.get("check_updates", True))
        self.v_startup = tk.BooleanVar(value=dv["_startup"])
        tk.Frame(b, bg=C["border"], height=1).grid(row=r, column=0, columnspan=3, sticky="ew", pady=(14, 4))
        r += 1
        label(b, f, "BOTH PROGRAMS", fg=C["muted"], font=f.small).grid(row=r, column=0, columnspan=3, sticky="w",
                                                                    pady=(0, 6))
        r += 1
        label(b, f, "NAME FORMAT").grid(row=r, column=0, sticky="w")
        flat_entry(b, f, 40, self.v_tmpl).grid(row=r, column=1, columnspan=2, sticky="ew", ipady=4)
        self.example = label(b, f, "", fg=C["accent"], font=f.small)
        self.example.grid(row=r + 1, column=1, columnspan=2, sticky="w", pady=(1, 0))
        label(b, f, "tokens: {name} {bpm} {key} {version} {date}", fg=C["muted"], font=f.small).grid(
            row=r + 2, column=1, columnspan=2, sticky="w", pady=(0, 8))
        r += 3

        for lab, opts, var in (("KEY STYLE", [("short", "Fm / F"), ("minmaj", "Fmin / Fmaj")], self.v_style),
                               ("ACCIDENTALS", [("mixed", "C# Eb F# Ab Bb"), ("sharps", "Sharps"),
                                                ("flats", "Flats")], self.v_acc),
                               ("DEFAULT", [("move", "Move to Beats"), ("copy", "Copy (keep original)")],
                                self.v_action)):
            label(b, f, lab).grid(row=r, column=0, sticky="w", pady=4)
            Segmented(b, f, opts, var).grid(row=r, column=1, columnspan=2, sticky="w", pady=4)
            r += 1

        tg = tk.Frame(b, bg=C["bg"])
        tg.grid(row=r, column=1, columnspan=2, sticky="w", pady=(6, 4))
        Toggle(tg, f, "Subfolder per beat", self.v_sub).pack(side="left", padx=(0, 18))
        Toggle(tg, f, "Date on beat folders", self.v_date).pack(side="left", padx=(0, 18))
        Toggle(tg, f, "Detect key from audio", self.v_detect).pack(side="left")
        r += 1
        tg2 = tk.Frame(b, bg=C["bg"])
        tg2.grid(row=r, column=1, columnspan=2, sticky="w", pady=(0, 4))
        Toggle(tg2, f, "Check for updates", self.v_updates).pack(side="left", padx=(0, 18))
        if sys.platform.startswith("win"):
            Toggle(tg2, f, "Start with Windows (watcher runs in the tray)", self.v_startup).pack(side="left")
        r += 1

        bot = tk.Frame(b, bg=C["bg"])
        bot.grid(row=r, column=0, columnspan=3, sticky="ew", pady=(16, 0))
        tk.Label(bot, text=f"v{__version__}", bg=C["bg"], fg=C["muted"], font=f.small).pack(side="left")
        FlatButton(bot, "SAVE" if not first_run else "START WATCHING", self.save, f, primary=True).pack(side="right")
        FlatButton(bot, "CANCEL" if not first_run else "QUIT", self.on_close, f).pack(side="right", padx=(0, 8))
        b.columnconfigure(1, weight=1)
        self.v_tmpl.trace_add("write", lambda *a: self.update_example())
        self.update_example()
        self.update_theme()
        self.bind("<Escape>", lambda e: self.on_close())
        self.show()

    def show(self):
        if not self.at:
            return super().show()
        self.update_idletasks()
        w = max(self.width, self.winfo_reqwidth())
        self.geometry(f"{w}x{self.winfo_reqheight()}+{self.at[0]}+{self.at[1]}")
        self.deiconify()
        self.lift()
        self.after(50, self.focus_force)

    # -- tabs
    def collect(self):
        """Copy what's on screen into the draft."""
        d, k = self.draft, lambda key: daw_key(self.daw, key)
        d[k("watch_folder")] = self.v_watch.get().strip()
        d[k("beats_folder")] = self.v_beats.get().strip()
        d[k("ignore_folders")] = [x.strip() for x in self.v_ign.get().split(",") if x.strip()]
        d[k("theme")], d[k("theme_file")], d[k("theme_colors")] = (self.v_theme.get(), self.theme_file,
                                                                   self.theme_colors)
        d[f"watch_{self.daw}"] = self.v_on.get()
        d.update(template=self.v_tmpl.get(), key_style=self.v_style.get(), accidentals=self.v_acc.get(),
                 action=self.v_action.get(), subfolder_per_beat=self.v_sub.get(), folder_date=self.v_date.get(),
                 detect_key=self.v_detect.get(), check_updates=self.v_updates.get(), _startup=self.v_startup.get())

    def switch(self, daw):
        if daw == self.daw:
            return
        self.collect()
        at = (self.winfo_x(), self.winfo_y())
        self.destroy()
        SettingsWindow(self.app, self.first_run, daw, self.draft, at, self.prev_daw)

    def render_default(self):
        if self.draft.get("default_daw", "fl") == self.daw:
            self.default_lbl.config(text="★  opens first", fg=C["muted"], cursor="")
        else:
            self.default_lbl.config(text="set as default", fg=C["accent"], cursor="hand2")

    def set_default(self):
        if self.draft.get("default_daw", "fl") == self.daw:
            return
        self.draft["default_daw"] = self.daw
        if not self.first_run:  # takes effect straight away, even without SAVE
            self.app.cfg["default_daw"] = self.daw
            save_json(CONFIG_PATH, self.app.cfg)
        self.render_default()
        self.app.toast(f"{DAW_NAMES[self.daw]} opens first from now on.")

    # -- theme
    def theme_cfg(self) -> dict:
        return {"daw": self.daw, "theme": self.v_theme.get(), "theme_file": self.theme_file,
                "theme_colors": self.theme_colors}

    def update_theme(self):
        if not hasattr(self, "theme_status"):
            return
        pal, status, _ = theme.resolve(self.theme_cfg())
        self.preview_palette = pal
        self.theme_status.config(text=status)
        self.swatch.delete("all")
        for i, k in enumerate(theme.SEEDS):
            self.swatch.create_rectangle(i * 16, 0, i * 16 + 13, 13, fill=pal[k], outline=C["border"])

    def load_theme_file(self):
        start = self.theme_file and str(Path(self.theme_file).parent)
        if self.daw == "ableton":
            dirs, kind, pattern, reader = theme.ableton_theme_dirs(), "Ableton Live theme", "*.ask", theme.read_ask
        else:
            dirs, kind, pattern, reader = theme.theme_dirs(), "FL Studio theme", "*.flstheme", theme.read_flstheme
        self.attributes("-topmost", False)
        p = filedialog.askopenfilename(parent=self, title=f"Choose an {kind}",
                                       initialdir=start or (str(dirs[0]) if dirs else str(Path.home())),
                                       filetypes=[(kind, pattern), ("All files", "*.*")])
        self.attributes("-topmost", True)
        if not p:
            return
        try:
            reader(p)
        except Exception as e:
            self.app.toast(f"Couldn't use that file: {e}")
            return
        self.theme_file = str(Path(p))
        self.theme_seg.set("file")

    def edit_colours(self):
        start = theme.seeds_of(getattr(self, "preview_palette", None) or C)

        def done(seeds):
            self.theme_colors = seeds
            self.theme_seg.set("custom")
        ThemeEditor(self.app, start, done, parent=self, default=theme.DEFAULTS[self.daw],
                    default_name=theme.DEFAULT_NAMES[self.daw])

    def browse(self, var):
        self.attributes("-topmost", False)
        p = filedialog.askdirectory(parent=self, initialdir=var.get() or str(Path.home()))
        self.attributes("-topmost", True)
        if p:
            var.set(str(Path(p)))

    def update_example(self):
        t = self.v_tmpl.get()
        ok = "{name}" in t and "{version}" in t
        ex = naming.build_stem(t, "Nightdrive", 140, "Fm", 3) + ".wav" if ok else "needs at least {name} and {version}"
        self.example.config(text=("e.g.  " if ok else "") + ex, fg=C["accent"] if ok else C["warn"])

    def save(self):
        t = self.v_tmpl.get()
        if "{name}" not in t or "{version}" not in t:
            return
        self.collect()
        startup = self.draft.pop("_startup", None)
        cfg = self.app.cfg
        cfg.update(self.draft)
        save_json(CONFIG_PATH, cfg)
        if sys.platform.startswith("win") and startup is not None and startup != startup_enabled():
            try:
                set_startup(startup)
            except Exception as e:
                logging.exception("startup toggle failed")
                self.app.toast(f"Couldn't change startup setting: {e}")
        self.destroy()
        self.app.apply_theme(daw=self.prev_daw)
        self.app.settings_saved()
        if self.first_run:
            self.app.start_watching()
            watched = [DAW_NAMES[k] for k in DAWS if watch_enabled(cfg, k)]
            self.app.toast(f"Watching for {' and '.join(watched)} exports. Find me in the system tray."
                           if watched else "Nothing to watch yet - turn on a program in Settings (tray icon).")
        else:
            self.app.refresh_watchers()

    def on_close(self):
        self.destroy()
        self.app.apply_theme(daw=self.prev_daw)  # drop any unsaved theme preview
        if self.first_run:
            self.app.quit()


# ----------------------------------------------------------- theme editor ----
class ThemeEditor(ThemedWindow):
    """Pick the five theme colours by hand, from a colour dialog, or off the screen."""

    def __init__(self, app, seeds: dict, on_done, parent=None, default=None, default_name="FL default"):
        super().__init__(app, "Theme · Colours", 470)
        self.on_done, self.parent_win = on_done, parent
        self.default = default or theme.FL_DEFAULT
        b, f = self.body, self.f
        label(b, f, "Click a swatch, type a hex code, or hit PICK and click\nthe matching spot in your FL Studio window.",
              fg=C["text"], font=f.body).grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 12))
        self.vars: dict[str, tk.StringVar] = {}
        self.swatches: dict[str, tk.Label] = {}
        for i, k in enumerate(theme.SEEDS, start=1):
            label(b, f, theme.SEED_LABELS[k].upper()).grid(row=i, column=0, sticky="w", padx=(0, 14), pady=3)
            sw = tk.Label(b, width=4, bg=seeds[k], cursor="hand2", relief="flat",
                          highlightthickness=1, highlightbackground=C["border"])
            sw.grid(row=i, column=1, sticky="ns", pady=3)
            sw.bind("<Button-1>", lambda e, k=k: self.choose(k))
            v = tk.StringVar(value=seeds[k])
            v.trace_add("write", lambda *a, k=k: self.changed(k))
            flat_entry(b, f, 9, v).grid(row=i, column=2, sticky="w", padx=(6, 6), ipady=3, pady=3)
            FlatButton(b, "PICK", lambda k=k: self.pick(k), f).grid(row=i, column=3, sticky="w", pady=3)
            self.vars[k], self.swatches[k] = v, sw

        self.preview = tk.Frame(b, highlightthickness=1)
        self.preview.grid(row=10, column=0, columnspan=4, sticky="ew", pady=(14, 0))
        self.render_preview()

        bot = tk.Frame(b, bg=C["bg"])
        bot.grid(row=11, column=0, columnspan=4, sticky="ew", pady=(16, 0))
        reset = tk.Label(bot, text=f"reset to {default_name}", bg=C["bg"], fg=C["muted"], font=f.small,
                         cursor="hand2")
        reset.pack(side="left")
        reset.bind("<Button-1>", lambda e: self.set_all(theme.seeds_of(self.default)))
        FlatButton(bot, "USE THESE", self.done, f, primary=True).pack(side="right")
        FlatButton(bot, "CANCEL", self.on_close, f).pack(side="right", padx=(0, 8))
        b.columnconfigure(3, weight=1)
        self.bind("<Escape>", lambda e: self.on_close())
        self.show()

    def seeds(self) -> dict:
        return {k: v.get().strip() for k, v in self.vars.items()}

    def set_all(self, seeds):
        for k, v in seeds.items():
            self.vars[k].set(v)

    def changed(self, k):
        v = self.vars[k].get().strip()
        if theme.is_hex(v):
            self.swatches[k].config(bg=theme.to_hex(theme.to_rgb(v)))
            self.render_preview()

    def render_preview(self):
        pal = theme.derive(self.seeds())
        p = self.preview
        for w in p.winfo_children():
            w.destroy()
        p.config(bg=pal["bg"], highlightbackground=pal["accent_dim"])
        bar = tk.Frame(p, bg=pal["panel"])
        bar.pack(fill="x")
        tk.Label(bar, text="PREVIEW", bg=pal["panel"], fg=pal["accent"], font=self.f.title).pack(side="left", padx=8,
                                                                                                pady=4)
        body = tk.Frame(p, bg=pal["bg"], padx=10, pady=8)
        body.pack(fill="x")
        tk.Label(body, text="NAME", bg=pal["bg"], fg=pal["accent_dim"], font=self.f.label).pack(side="left")
        tk.Label(body, text="Nightdrive", bg=pal["field"], fg=pal["text"], font=self.f.body, padx=8,
                 pady=2).pack(side="left", padx=8)
        tk.Label(body, text="SKIP", bg=pal["field"], fg=pal["btn_text"], font=self.f.button, padx=10,
                 pady=3).pack(side="right")
        tk.Label(body, text="SAVE", bg=pal["accent"], fg=pal["on_accent"], font=self.f.button, padx=10,
                 pady=3).pack(side="right", padx=6)
        tk.Label(p, text="from project name", bg=pal["bg"], fg=pal["muted"], font=self.f.small,
                 anchor="w").pack(fill="x", padx=10, pady=(0, 8))

    def choose(self, k):
        from tkinter import colorchooser
        self.attributes("-topmost", False)
        try:
            res = colorchooser.askcolor(color=self.vars[k].get(), parent=self, title=theme.SEED_LABELS[k])
        finally:
            self.attributes("-topmost", True)
        if res and res[1]:
            self.vars[k].set(res[1])

    def pick(self, k):
        hide = [w for w in (self, self.parent_win) if w is not None and w.winfo_exists()]
        ScreenPicker.start(self.app, lambda hx, k=k: self.vars[k].set(hx), hide)

    def done(self):
        bad = [theme.SEED_LABELS[k] for k, v in self.seeds().items() if not theme.is_hex(v)]
        if bad:
            self.app.toast(f"Not a colour: {', '.join(bad)} (use #rrggbb)")
            return
        seeds = {k: theme.to_hex(theme.to_rgb(v)) for k, v in self.seeds().items()}
        self.destroy()
        self.on_done(seeds)


def virtual_screen(root) -> tuple[int, int, int, int]:
    """(x, y, w, h) of the whole desktop - every monitor on Windows."""
    if sys.platform.startswith("win"):
        try:
            import ctypes
            m = ctypes.windll.user32.GetSystemMetrics
            w, h = m(78), m(79)
            if w and h:
                return m(76), m(77), w, h
        except Exception:
            pass
    return 0, 0, root.winfo_screenwidth(), root.winfo_screenheight()


class ScreenPicker(tk.Toplevel):
    """Eyedropper: freezes a snapshot of the screen, click any pixel to take its colour.
    Esc or right-click cancels. Our own windows are hidden while the snapshot is taken."""

    ZOOM, CELLS = 12, 11

    @classmethod
    def start(cls, app, callback, hide=()):
        for w in hide:
            w.withdraw()

        def restore():
            for w in hide:
                if w.winfo_exists():
                    w.deiconify()
                    w.lift()

        def grab():
            try:
                from PIL import ImageGrab
                x, y, w, h = virtual_screen(app.root)
                img = ImageGrab.grab(all_screens=True) if sys.platform.startswith("win") else ImageGrab.grab()
                cls(app, img.convert("RGB"), (x, y, w, h), callback, restore)
            except Exception as e:
                logging.exception("screen picker failed")
                restore()
                app.toast(f"Couldn't capture the screen ({type(e).__name__}). Type the colour in instead.")
        app.root.after(350, grab)

    def __init__(self, app, img, box, callback, restore):
        from PIL import Image, ImageTk
        super().__init__(app.root)
        self.app, self.img, self.callback, self.restore = app, img, callback, restore
        self._Image, self._ImageTk = Image, ImageTk
        x, y, w, h = box
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.cv = tk.Canvas(self, width=w, height=h, highlightthickness=0, cursor="crosshair", bd=0)
        self.cv.pack()
        self.shot = ImageTk.PhotoImage(img)
        self.cv.create_image(0, 0, image=self.shot, anchor="nw")
        side = self.ZOOM * self.CELLS
        self.loupe_img = None
        self.loupe = self.cv.create_image(0, 0, anchor="nw")
        self.frame = self.cv.create_rectangle(0, 0, side, side, outline=C["accent"], width=2)
        self.centre = self.cv.create_rectangle(0, 0, 0, 0, outline="#ffffff", width=1)
        self.tag_bg = self.cv.create_rectangle(0, 0, 0, 0, fill=C["panel"], outline=C["accent"])
        self.tag = self.cv.create_text(0, 0, anchor="nw", fill=C["text"], font=app.fonts.small)
        self.hint = self.cv.create_text(w // 2, 24, text="click a colour  ·  Esc to cancel", fill=C["text"],
                                        font=app.fonts.title)
        x1, y1, x2, y2 = self.cv.bbox(self.hint)
        self.cv.tag_lower(self.cv.create_rectangle(x1 - 12, y1 - 6, x2 + 12, y2 + 6, fill=C["panel"],
                                                   outline=C["accent"]), self.hint)
        self.cv.bind("<Motion>", self.move)
        self.cv.bind("<Button-1>", self.take)
        for seq in ("<Escape>", "<Button-3>"):
            self.bind(seq, lambda e: self.finish(None))
        self.after(30, self.focus_force)

    def colour_at(self, x, y) -> str:
        x = max(0, min(self.img.width - 1, x))
        y = max(0, min(self.img.height - 1, y))
        return theme.to_hex(self.img.getpixel((x, y)))

    def move(self, e):
        n, z = self.CELLS, self.ZOOM
        half = n // 2
        crop = self.img.crop((e.x - half, e.y - half, e.x + half + 1, e.y + half + 1))
        self.loupe_img = self._ImageTk.PhotoImage(crop.resize((n * z, n * z), self._Image.NEAREST))
        side = n * z
        lx = e.x + 24 if e.x + 24 + side < self.img.width else e.x - 24 - side
        ly = e.y + 24 if e.y + 24 + side + 26 < self.img.height else e.y - 24 - side - 26
        self.cv.itemconfig(self.loupe, image=self.loupe_img)
        self.cv.coords(self.loupe, lx, ly)
        self.cv.coords(self.frame, lx, ly, lx + side, ly + side)
        self.cv.coords(self.centre, lx + half * z, ly + half * z, lx + (half + 1) * z, ly + (half + 1) * z)
        hx = self.colour_at(e.x, e.y)
        self.cv.itemconfig(self.tag, text=f"  {hx}")
        self.cv.coords(self.tag, lx, ly + side + 4)
        self.cv.coords(self.tag_bg, lx, ly + side + 2, lx + side, ly + side + 24)
        self.cv.itemconfig(self.tag_bg, fill=hx)
        self.cv.itemconfig(self.tag, fill="#000000" if theme.luminance(hx) > 0.35 else "#ffffff")
        for item in (self.frame, self.centre, self.tag_bg, self.tag):
            self.cv.tag_raise(item)

    def take(self, e):
        self.finish(self.colour_at(e.x, e.y))

    def finish(self, hx):
        self.destroy()
        self.restore()
        if hx:
            self.callback(hx)


# ------------------------------------------------------------------ toast ----
class Toast(tk.Toplevel):
    def __init__(self, app, text, folder=None, seconds=4.0, link=None):
        super().__init__(app.root)
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.configure(bg=C["accent"])
        inner = tk.Frame(self, bg=C["panel"], padx=14, pady=10)
        inner.pack(padx=(3, 0), pady=0)
        tk.Label(inner, text=text, bg=C["panel"], fg=C["text"], font=app.fonts.body, justify="left",
                 wraplength=380).pack(anchor="w")
        if folder:
            open_lbl = tk.Label(inner, text="open folder", bg=C["panel"], fg=C["accent"], font=app.fonts.small,
                                cursor="hand2")
            open_lbl.pack(anchor="w", pady=(4, 0))
            open_lbl.bind("<Button-1>", lambda e: app.safe_open(folder, make=True))
        if link:
            label_text, url = link
            lk = tk.Label(inner, text=label_text, bg=C["panel"], fg=C["accent"], font=app.fonts.small,
                          cursor="hand2")
            lk.pack(anchor="w", pady=(4, 0))
            lk.bind("<Button-1>", lambda e: (open_url(url), self.destroy()))
        self.update_idletasks()
        w, h = self.winfo_reqwidth(), self.winfo_reqheight()
        self.geometry(f"+{self.winfo_screenwidth() - w - 24}+{self.winfo_screenheight() - h - 70}")
        self.after(int(seconds * 1000), self.destroy)


def logo_image(size: int = 64):
    """The bars logo in the current theme colours (tray + window icon)."""
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    bg, acc = theme.to_rgb(theme.mix(C["field"], "#000000", 0.35)), theme.to_rgb(C["accent"])
    d.rounded_rectangle((2, 2, 62, 62), 12, fill=bg + (255,), outline=acc + (255,), width=3)
    for i, h in enumerate((16, 32, 42, 24, 34)):
        x = 12 + i * 9
        d.rectangle((x, 52 - h, x + 5, 52), fill=acc + (255,))
    return img if size == 64 else img.resize((size, size), Image.LANCZOS)


def _mtime(p) -> float | None:
    try:
        return os.stat(p).st_mtime if p else None
    except OSError:
        return None


# -------------------------------------------------------------------- app ----
class App:
    def __init__(self, root=None):
        self.root = root or tk.Tk()
        self.root.withdraw()
        self.root.title(APP)
        self.fonts = Fonts(self.root)
        self.cfg = load_config()
        self.daw = self.cfg.get("default_daw") if self.cfg.get("default_daw") in DAWS else "fl"  # whose colours
        self.theme_src, self.theme_mtime, self._theme_seen = None, None, None
        self.tray = None  # before apply_theme(): a theme that differs from the stock look rethemes the tray
        self.apply_theme()
        self.state = load_json(STATE_PATH, {"projects": {}, "ignored_paths": []})
        self.ui_q: queue.Queue = queue.Queue()
        self.jobs: list[Job] = []
        self.popup = None
        self.paused = False
        self.undo_stack: list[list] = []
        self.own_outputs: set[str] = set()   # files we wrote - no watcher treats them as new exports
        self.watchers = {d: ExportWatcher(self, d) for d in DAWS}
        self.watching = False
        self.root.after(100, self.pump)
        self.root.after(THEME_POLL_MS, self.watch_theme)

    def dcfg(self, daw=None) -> dict:
        return daw_cfg(self.cfg, daw or self.daw)

    # -- theme
    def apply_theme(self, announce=False, cfg=None, daw=None) -> bool:
        """Load a program's palette into C (daw: switch program; cfg: preview unsaved settings).
        True if the colours changed."""
        if daw in DAWS:
            self.daw = daw
        try:
            pal, status, src = theme.resolve(cfg or self.dcfg())
        except Exception:
            logging.exception("theme failed - using the default")
            pal = dict(theme.DEFAULTS[self.daw])
            status, src = theme.DEFAULT_NAMES[self.daw], None
        changed = pal != C
        C.clear()
        C.update(pal)
        self.theme_status, self.theme_src = status, src
        self.theme_mtime = self._theme_seen = _mtime(src)
        if changed:
            logging.info("theme: %s", status)
            self.retheme()
            if announce:
                self.toast(f"Colours updated to match {DAW_NAMES[self.daw]}.")
        return changed

    def set_daw(self, daw) -> bool:
        """Switch to a program's colours. True if anything on screen was rethemed."""
        if daw == self.daw:
            return False
        return self.apply_theme(daw=daw)

    def watch_theme(self):
        """Every few seconds: has FL (or the chosen file) written a new theme?"""
        try:
            mode = self.dcfg().get("theme", "auto")
            src = self.theme_src
            if mode == "auto":
                src = theme.auto_source(self.daw)
            m = _mtime(src)
            if src != self.theme_src or m != self.theme_mtime:
                if m == self._theme_seen:       # unchanged for one tick = FL has finished writing it
                    self.apply_theme(announce=False)
                self._theme_seen = m
        except Exception:
            logging.exception("theme watch failed")
        self.root.after(THEME_POLL_MS, self.watch_theme)

    def retheme(self):
        """Colours changed: refresh what stays on screen. Popups pick it up next time."""
        if getattr(self, "tray", None) is not None:
            try:
                self.tray.icon = logo_image()
            except Exception:
                logging.exception("tray icon refresh failed")

    # thread-safe hand-off into the Tk thread
    def call(self, fn):
        self.ui_q.put(fn)

    def pump(self):
        try:
            while True:
                self.ui_q.get_nowait()()
        except queue.Empty:
            pass
        except Exception:
            logging.exception("ui task failed")
        self.root.after(100, self.pump)

    def start_watching(self):
        self.watching = True
        self.refresh_watchers()

    def refresh_watchers(self):
        """Start / stop / move each program's watcher to match the config."""
        if not self.watching:
            return
        for d, w in self.watchers.items():
            want = watch_enabled(self.cfg, d)
            root = str(Path(self.dcfg(d)["watch_folder"]))
            if w.observer is not None and (not want or w.root != root):
                w.stop()
                logging.info("stopped watching %s", w.root)
            if want and w.observer is None:
                try:
                    w.start()
                except Exception as e:
                    logging.exception("watcher failed")
                    self.toast(f"Couldn't watch {root}: {e}")

    def submit_files(self, files, daw="fl"):  # called from watcher thread
        self.call(lambda f=files, d=daw: self.enqueue(f, d))

    def enqueue(self, files, daw="fl"):
        try:
            job = build_job(files, self.dcfg(daw), self.state)
        except Exception:
            logging.exception("build_job failed for %s", files)
            return
        logging.info("job (%s): %s files, name=%s bpm=%s key=%s", daw, len(job.files), job.name, job.bpm, job.key)
        self.jobs.append(job)
        self.next_popup()

    def next_popup(self):
        if self.popup is not None and self.popup.winfo_exists():
            self.popup.badge.config(text=f"+{len(self.jobs)} waiting" if self.jobs else "")
            return
        if not self.jobs:
            return
        job = self.jobs.pop(0)
        self.set_daw(job.daw)  # the popup wears the colours of the program the export came from
        self.popup = ExportPopup(self, job)
        if self.jobs:
            self.popup.badge.config(text=f"+{len(self.jobs)} waiting")
        if job.detect_file and (self.cfg["detect_key"] or job.detect_bpm):
            threading.Thread(target=self.detect, args=(self.popup, job), daemon=True).start()
        elif job.detect_bpm:
            self.popup.set_bpm_detection([], "format not readable")

    def estimate_bpm(self, popup, job):
        """Popup asked for an audio tempo estimate on top of the project's BPM."""
        threading.Thread(target=self.detect, args=(popup, job, True), daemon=True).start()

    def detect(self, popup, job, bpm_only=False):
        bpm = None
        try:
            bpm = float(job.bpm) if job.bpm else None
        except ValueError:
            pass
        if job.detect_bpm or bpm_only:
            try:
                from bpm_detect import estimate_bpm
                res = estimate_bpm(str(job.detect_file))
                bpm = bpm or (res[0][0] if res else None)
                self.call(lambda r=res: popup.set_bpm_detection(r))
            except Exception as e:
                logging.exception("bpm estimate failed")
                msg = type(e).__name__
                self.call(lambda m=msg: popup.set_bpm_detection([], m))
        if bpm_only or not self.cfg["detect_key"]:
            return
        try:
            from key_detect import detect_key
            keys = detect_key(str(job.detect_file), self.cfg["key_style"], self.cfg["accidentals"], 3, bpm)
            self.call(lambda k=keys: popup.set_detection(k))
        except Exception as e:
            logging.exception("key detection failed")
            msg = type(e).__name__
            self.call(lambda m=msg: popup.set_detection([], m))

    def default_keep(self) -> bool:
        return self.cfg["action"] == "copy"

    def settings_saved(self):
        pass

    def popup_closed(self, job=None, saved=False):
        self.popup = None
        self.root.after(150, self.next_popup)

    def apply(self, job, pairs, keep, name, bpm, key, version, folder) -> bool:
        done = []
        try:
            for src, dst in pairs:
                dst.parent.mkdir(parents=True, exist_ok=True)
                if dst.exists() and os.path.samefile(src, dst):
                    continue  # already named and filed exactly like this
                dst = naming.unique_path(dst)
                self.own_outputs.add(str(dst).lower())
                for attempt in range(20):
                    try:
                        if keep:
                            shutil.copy2(src, dst)
                        else:
                            shutil.move(str(src), str(dst))
                        break
                    except PermissionError:
                        if attempt == 19:
                            raise
                        time.sleep(0.5)
                done.append((str(src), str(dst), "copy" if keep else "move"))
                logging.info("%s %s -> %s", "copied" if keep else "moved", src, dst)
        except Exception as e:
            logging.exception("apply failed")
            self.toast(f"Couldn't save: {e}")
            if done:
                self.undo_stack.append(done)
            return False
        self.undo_stack.append(done)
        self.last_done = done
        if not done:
            self.toast("Already named and filed - nothing to do.")
            return True
        if job.project_key:
            self.state.setdefault("projects", {})[job.project_key] = {
                "name": name, "key": key, "bpm": bpm, "last_version": version, "updated": time.time(),
                "daw": job.daw, "als_key": job.als_key}
            save_json(STATE_PATH, self.state)
        shown = Path(done[0][1]).name if job.kind == "single" else Path(done[0][1]).parent.name + "/"
        self.toast(f"Saved  {shown}", folder=folder)
        return True

    def undo_last(self):
        if not self.undo_stack:
            self.toast("Nothing to undo.")
            return
        ops = self.undo_stack.pop()
        for src, dst, mode in reversed(ops):
            try:
                if mode == "copy":
                    os.remove(dst)
                else:
                    back = naming.unique_path(Path(src))
                    self.own_outputs.add(str(back).lower())  # don't treat it as a new export
                    shutil.move(dst, back)
                parent = Path(dst).parent
                if parent.name.endswith("_stems") and not any(parent.iterdir()):
                    parent.rmdir()
            except Exception as e:
                logging.warning("undo failed for %s: %s", dst, e)
        self.toast(f"Undid last rename ({len(ops)} file{'s' * (len(ops) > 1)}).")

    def safe_open(self, p, make=False):
        try:
            open_path(p, make=make)
        except Exception as e:
            logging.warning("couldn't open %s: %s", p, e)
            self.toast(f"Couldn't open {short(str(p), 50)}: {e}")

    def check_updates_later(self, delay_ms: int = 6000):
        """Once a day, in the background: tell the user if a newer release is on GitHub."""
        if not self.cfg.get("check_updates", True):
            return
        last = self.state.get("last_update_check", 0)
        if time.time() - last < UPDATE_EVERY_HOURS * 3600:
            return

        def work():
            res = fetch_latest_release()
            self.call(lambda r=res: self._update_result(r))
        self.root.after(delay_ms, lambda: threading.Thread(target=work, daemon=True).start())

    def _update_result(self, res):
        self.state["last_update_check"] = time.time()
        save_json(STATE_PATH, self.state)
        if not res:
            return
        latest, url = res
        if version_tuple(latest) > version_tuple(__version__):
            logging.info("update available: %s (running %s)", latest, __version__)
            try:
                Toast(self, f"FL Export Namer {latest} is out (you have {__version__}).", seconds=12,
                      link=("download the update", url))
            except Exception:
                logging.exception("update toast failed")

    def toast(self, text, folder=None):
        try:
            Toast(self, text, folder)
        except Exception:
            logging.exception("toast failed")

    def settings(self, first_run=False, daw=None):
        SettingsWindow(self, first_run, daw)

    def toggle_pause(self):
        self.paused = not self.paused
        self.toast("Paused - exports will be left alone." if self.paused else "Watching again.")

    # -- tray
    def start_tray(self):
        try:
            import pystray
        except Exception as e:  # missing package, or no tray backend on this OS
            logging.warning("no tray icon (%s) - running without one", e)
            return
        img = logo_image()
        M = pystray.MenuItem
        def first():
            return self.cfg.get("default_daw", "fl")

        def second():
            return next(d for d in DAWS if d != first())

        def open_beats(pick):
            self.call(lambda: self.safe_open(self.dcfg(pick())["beats_folder"], make=True))
        menu = pystray.Menu(
            M(lambda i: f"Open {DAW_NAMES[first()]} beats folder", lambda: open_beats(first), default=True),
            M(lambda i: f"Open {DAW_NAMES[second()]} beats folder", lambda: open_beats(second),
              visible=lambda i: watch_enabled(self.cfg, second())),
            M("Open Beat Sorter", lambda: launch_sorter()),
            M("Undo last rename", lambda: self.call(self.undo_last)),
            M("Pause watching", lambda: self.call(self.toggle_pause), checked=lambda i: self.paused),
            pystray.Menu.SEPARATOR,
            M("Settings…", lambda: self.call(self.settings)),
            M("Open log", lambda: self.call(lambda: self.safe_open(LOG_PATH))),
            M("Quit", lambda: self.call(self.quit)),
        )
        try:
            self.tray = pystray.Icon("fl_export_namer", img, APP, menu)
            threading.Thread(target=self.tray.run, daemon=True).start()
        except Exception:
            logging.exception("tray icon failed")

    def quit(self):
        try:
            for w in self.watchers.values():
                w.stop()
            if self.tray:
                self.tray.stop()
        finally:
            self.root.quit()

    def run(self, demo=False, test_file=None):
        if demo:
            self.demo(demo if demo in DAWS else "fl")
        elif test_file:
            self.enqueue([Path(test_file)], project_daw_near(Path(test_file).parent) or "fl")
        elif not CONFIG_PATH.exists():
            self.settings(first_run=True)
        else:
            self.start_watching()
        if not demo and not test_file:
            self.start_tray()
            self.check_updates_later()
        self.root.mainloop()

    def demo(self, daw="fl"):
        if daw == "ableton":
            job = Job(files=[Path("Nightdrive.wav")], daw="ableton", name="Nightdrive",
                      name_source="from project name", bpm="92", bpm_source="read from Ableton set",
                      key="Fm", key_source=ALS_KEY_SOURCES["scale"], project=Path("Nightdrive.als"),
                      bpm_trusted=True, als_info=AlsInfo(92.0, "project", 5, True, "Minor", "scale", "12.1.5"),
                      detect_file=Path("Nightdrive.wav"))
        else:
            job = Job(files=[Path("Nightdrive_2.wav"), Path("Nightdrive_2.mp3")], name="Nightdrive",
                      name_source="from project name", bpm="140", bpm_source="read from project",
                      key="", key_source="", project=Path("Nightdrive_2.flp"), bpm_trusted=True,
                      flp_info=FlpInfo(140.0, "project", "", "", "26.1.5.5618"))
        self.set_daw(daw)
        self.popup = ExportPopup(self, job)
        self.root.after(700, lambda: self.popup.set_detection([("Fm", .71), ("Ab", .19), ("Cm", .06)]))
        self.popup.e_name.bind("<Destroy>", lambda e: self.root.after(200, self.root.quit))


def single_instance() -> socket.socket | None:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", 47613))
        s.listen(1)
        return s
    except OSError:
        return None


def main():
    APPDIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=LOG_PATH, level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.info("FL Export Namer v%s starting%s", __version__, " (installed build)" if FROZEN else "")
    if sys.platform.startswith("win"):
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    args = sys.argv[1:]
    demo = ("ableton" if "--ableton" in args else "fl") if "--demo" in args else False
    test_file = args[args.index("--test") + 1] if "--test" in args and len(args) > args.index("--test") + 1 else None
    lock = None
    if not demo and not test_file:
        lock = single_instance()
        if lock is None:
            return  # already running
    App().run(demo=demo, test_file=test_file)


if __name__ == "__main__":
    main()
