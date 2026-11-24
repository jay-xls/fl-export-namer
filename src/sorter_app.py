"""Beat Sorter (importable module) - drop old exports in, get BPM + key estimates from the audio,
confirm in the same popup as DAW Export Fixer, and file them into FL Export.

No FL project needed. Run:
    pyw beat_sorter.pyw                      (opens the drop window)
    pyw beat_sorter.pyw "a.wav" "D:\\old"    (or drop files/folders on its shortcut)
"""

from __future__ import annotations

import logging
import socket
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import naming  # noqa: E402
import theme  # noqa: E402
from namer_core import (APPDIR, AUDIO_EXTS, CONFIG_PATH, DAW_NAMES, DAWS, DETECTABLE, FROZEN,  # noqa: E402
                        LOG_PATH, App, C, Job, Segmented, SettingsWindow, Toggle, __version__, daw_cfg,
                        label, logo_image, migrate_old_name, save_json, short)

PORT = 47614
MAX_RECENT = 7


def make_root():
    try:
        from tkinterdnd2 import TkinterDnD
        return TkinterDnD.Tk(), True
    except Exception as e:  # not installed / Tk extension failed to load
        logging.warning("drag and drop unavailable: %s", e)
        return tk.Tk(), False


def dark_titlebar(win):
    """Windows 10/11: caption in the theme colours. Silently skipped elsewhere."""
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes
        win.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id())
        dwm = ctypes.windll.dwmapi.DwmSetWindowAttribute
        dark = int(theme.luminance(C["panel"]) < 0.35)
        for attr, val in ((20, dark), (35, theme.colorref(C["panel"])), (36, theme.colorref(C["accent"])),
                          (34, theme.colorref(C["accent_dim"]))):
            v = ctypes.c_int(val)
            dwm(hwnd, attr, ctypes.byref(v), ctypes.sizeof(v))
    except Exception:
        pass


def collect_audio(paths) -> list[Path]:
    out = []
    for p in map(Path, paths):
        if p.is_dir():
            out += sorted(q for q in p.rglob("*") if q.is_file() and q.suffix.lower() in AUDIO_EXTS)
        elif p.is_file() and p.suffix.lower() in AUDIO_EXTS:
            out.append(p)
    return list(dict.fromkeys(out))


def group_files(files: list[Path]) -> list[list[Path]]:
    """Same name + same folder, different formats (beat.wav + beat.mp3) = one beat."""
    groups: dict = {}
    for f in files:
        groups.setdefault((str(f.parent).lower(), f.stem.lower()), []).append(f)
    return list(groups.values())


def build_standalone_job(files: list[Path], cfg: dict) -> Job:
    """cfg as daw_cfg() returns it - the beat is filed into that program's beats folder."""
    files = sorted(files, key=lambda p: (p.suffix.lower() != ".wav", p.name.lower()))
    hints = naming.parse_hints(files[0].stem, cfg["template"], cfg["key_style"])
    job = Job(files=files, standalone=True, detect_bpm=True, daw=cfg.get("daw", "fl"),
              context=("FOLDER", short(str(files[0].parent))))
    job.name = hints.get("name") or files[0].stem
    job.name_source = ("unnamed - give it a name" if naming.is_generic(job.name)
                       else "from file name - tidy it up if needed")
    if hints.get("bpm"):
        job.bpm, job.bpm_source = naming.fmt_bpm(hints["bpm"]), "from file name"
    if hints.get("key"):
        job.key, job.key_source = hints["key"], "from file name"
    by_ext = {f.suffix.lower(): f for f in files}
    job.detect_file = next((by_ext[e] for e in DETECTABLE if e in by_ext), None)
    return job


class SorterApp(App):
    def __init__(self):
        root, self.dnd = make_root()
        super().__init__(root)
        self.popup_title = "Beat Sorter"
        self.keep_var = tk.BooleanVar(value=self.cfg["action"] == "copy")
        self.recent: list[tuple[str, str]] = []
        self.build_window()

    # -- hooks into the shared popup
    def default_keep(self) -> bool:
        return self.keep_var.get()

    def popup_closed(self, job=None, saved=False):
        if job is not None:
            if saved and getattr(self, "last_done", None):
                first = Path(self.last_done[0][1])
                self.add_recent("✓", first.name + (f"  (+{len(self.last_done) - 1})" if len(self.last_done) > 1 else ""))
            elif saved:
                self.add_recent("=", job.files[0].name + "  (already filed)")
            else:
                self.add_recent("–", job.files[0].name + "  skipped")
        super().popup_closed(job, saved)
        self.root.after(200, self.update_status)

    def settings_saved(self):
        self.dest_lbl.config(text=short(self.dcfg()["beats_folder"], 52))
        self.render_default()

    # -- program tabs: which beats folder drops go to, and whose colours the window wears
    def switch_daw(self, daw):
        if daw == self.daw:
            return
        if not self.set_daw(daw):   # identical palettes: nothing was rebuilt, refresh by hand
            self.retheme(force=True)

    def set_default(self):
        if self.cfg.get("default_daw", "fl") == self.daw:
            return
        self.cfg["default_daw"] = self.daw
        save_json(CONFIG_PATH, self.cfg)
        self.render_default()
        self.toast(f"Beat Sorter opens on {DAW_NAMES[self.daw]} from now on.")

    def render_default(self):
        if self.cfg.get("default_daw", "fl") == self.daw:
            self.default_lbl.config(text="★ default", fg=C["muted"], cursor="")
        else:
            self.default_lbl.config(text="set as default", fg=C["accent"], cursor="hand2")

    # -- window
    def build_window(self):
        r, f = self.root, self.fonts
        r.title("Beat Sorter")
        r.configure(bg=C["bg"])
        if not getattr(self, "_built", False):  # a re-theme rebuild keeps the user's window size
            r.geometry("600x560")
            r.minsize(520, 480)
            self._built = True
        self.set_icon()

        head = tk.Frame(r, bg=C["panel"], height=44)
        head.pack(fill="x")
        head.pack_propagate(False)
        logo = tk.Canvas(head, width=20, height=20, bg=C["panel"], highlightthickness=0)
        logo.pack(side="left", padx=(14, 8))
        for i, h in enumerate((7, 13, 18, 10, 15)):
            logo.create_rectangle(1 + i * 4, 19 - h, 3.5 + i * 4, 19, fill=C["accent"], width=0)
        tk.Label(head, text="BEAT SORTER", bg=C["panel"], fg=C["accent"], font=f.title).pack(side="left")
        tk.Label(head, text=f"v{__version__}", bg=C["panel"], fg=C["muted"], font=f.small).pack(side="right", padx=14)
        self.v_daw = tk.StringVar(value=self.daw)
        self.default_lbl = tk.Label(head, text="", bg=C["panel"], font=f.small)
        self.default_lbl.pack(side="right", padx=(8, 4))
        self.default_lbl.bind("<Button-1>", lambda e: self.set_default())
        Segmented(head, f, [(k, DAW_NAMES[k].upper()) for k in DAWS], self.v_daw,
                  command=lambda: self.switch_daw(self.v_daw.get())).pack(side="right", padx=(12, 0))
        self.render_default()
        tk.Frame(r, bg=C["border"], height=1).pack(fill="x")
        tk.Label(r, text="BPM + key from the audio  ·  rename  ·  file it", bg=C["bg"], fg=C["muted"],
                 font=f.small, anchor="w", padx=18).pack(fill="x", pady=(8, 0))

        body = tk.Frame(r, bg=C["bg"], padx=18, pady=16)
        body.pack(fill="both", expand=True)

        self.zone = tk.Canvas(body, height=190, bg=C["field"], highlightthickness=0, cursor="hand2")
        self.zone.pack(fill="x")
        self.zone.bind("<Configure>", lambda e: self.draw_zone())
        self.zone.bind("<Button-1>", lambda e: self.browse())
        self.zone_hot = False
        if self.dnd:
            from tkinterdnd2 import DND_FILES
            first = not getattr(self, "_root_dnd", False)
            self._root_dnd = True
            for w in (self.zone, r) if first else (self.zone,):
                w.drop_target_register(DND_FILES)
                w.dnd_bind("<<Drop>>", self.on_drop)
                w.dnd_bind("<<DropEnter>>", lambda e: self.hot(True))
                w.dnd_bind("<<DropLeave>>", lambda e: self.hot(False))

        self.status = tk.Label(body, text="", bg=C["bg"], fg=C["muted"], font=f.small, anchor="w")
        self.status.pack(fill="x", pady=(8, 0))

        hdr = tk.Frame(body, bg=C["bg"])
        hdr.pack(fill="x", pady=(14, 4))
        label(hdr, f, "RECENT").pack(side="left")
        for txt, cmd in (("undo last", self.undo_last), ("clear queue", self.clear_queue)):
            lb = tk.Label(hdr, text=txt, bg=C["bg"], fg=C["muted"], font=f.small, cursor="hand2")
            lb.pack(side="right", padx=(12, 0))
            lb.bind("<Button-1>", lambda e, c=cmd: (c(), self.update_status()))
            lb.bind("<Enter>", lambda e, w=lb: w.config(fg=C["accent"]))
            lb.bind("<Leave>", lambda e, w=lb: w.config(fg=C["muted"]))
        self.recent_box = tk.Frame(body, bg=C["deep"], highlightthickness=1, highlightbackground=C["border"],
                                   padx=12, pady=8)
        self.recent_box.pack(fill="both", expand=True)

        foot = tk.Frame(r, bg=C["panel"], padx=18, pady=10)
        foot.pack(fill="x", side="bottom")
        label(foot, f, "SAVES TO").pack(side="left")
        self.dest_lbl = tk.Label(foot, text=short(self.dcfg()["beats_folder"], 52), bg=C["panel"], fg=C["text"],
                                 font=f.small, cursor="hand2")
        self.dest_lbl.pack(side="left", padx=(8, 0))
        self.dest_lbl.bind("<Button-1>", lambda e: self.safe_open(self.dcfg()["beats_folder"], make=True))
        for txt, cmd in (("settings", lambda: SettingsWindow(self, daw=self.daw)),
                         ("log", lambda: self.safe_open(LOG_PATH))):
            ch = tk.Label(foot, text=txt, bg=C["panel"], fg=C["muted"], font=f.small, cursor="hand2")
            ch.pack(side="left", padx=(10, 0))
            ch.bind("<Button-1>", lambda e, c=cmd: c())
        Toggle(foot, f, "Keep originals", self.keep_var).pack(side="right")

        self.render_recent()
        self.update_status()
        r.deiconify()  # the shared App starts hidden (the watcher lives in the tray)
        dark_titlebar(r)

    def set_icon(self):
        try:
            from PIL import ImageTk
            self._icon = ImageTk.PhotoImage(logo_image())
            self.root.iconphoto(True, self._icon)
        except Exception:
            pass

    def retheme(self, force=False):
        if not force:
            super().retheme()
        if getattr(self, "zone", None) is None:
            return  # window not built yet
        for w in self.root.winfo_children():
            if not isinstance(w, tk.Toplevel):
                w.destroy()
        self.build_window()

    def draw_zone(self):
        z, f = self.zone, self.fonts
        z.delete("all")
        w, h = z.winfo_width(), z.winfo_height()
        z.configure(bg=C["field_hi"] if self.zone_hot else C["field"])
        z.create_rectangle(8, 8, w - 8, h - 8, outline=C["accent"] if self.zone_hot else C["accent_dim"],
                           dash=(6, 4), width=2)
        for i, bh in enumerate((14, 26, 36, 20, 30)):
            x = w / 2 - 22 + i * 9
            z.create_rectangle(x, h / 2 - 22 - bh / 2, x + 5, h / 2 - 22 + bh / 2, fill=C["accent"], width=0)
        z.create_text(w / 2, h / 2 + 18, text="DROP BEATS HERE", fill=C["accent"],
                      font=(f.preview[0], 15, "bold"))
        sub = "audio files or whole folders  ·  or click to browse"
        if not self.dnd:
            sub = "click to choose files (drag-and-drop unavailable - " + (
                "reinstall the app)" if FROZEN else "run setup.bat)")
        z.create_text(w / 2, h / 2 + 44, text=sub, fill=C["muted"], font=f.small)

    def hot(self, on):
        self.zone_hot = on
        self.draw_zone()
        return "copy"

    def on_drop(self, e):
        self.hot(False)
        self.add_paths(self.root.tk.splitlist(e.data))
        return "copy"

    def browse(self):
        exts = " ".join(f"*{x}" for x in sorted(AUDIO_EXTS))
        paths = filedialog.askopenfilenames(parent=self.root, title="Choose exports to sort",
                                            filetypes=[("Audio", exts), ("All files", "*.*")])
        if paths:
            self.add_paths(paths)

    def add_paths(self, paths):
        files = collect_audio(paths)
        if not files:
            self.toast("No audio files in that drop.")
            return
        groups = group_files(files)
        for g in groups:
            try:
                self.jobs.append(build_standalone_job(g, daw_cfg(self.cfg, self.daw)))
            except Exception:
                logging.exception("couldn't queue %s", g)
        logging.info("queued %d beats (%d files)", len(groups), len(files))
        self.next_popup()
        self.update_status()

    def clear_queue(self):
        n = len(self.jobs)
        self.jobs.clear()
        if self.popup is not None and self.popup.winfo_exists():
            self.popup.badge.config(text="")
        self.toast(f"Cleared {n} waiting." if n else "Queue already empty.")

    def add_recent(self, mark, text):
        self.recent.insert(0, (mark, text))
        del self.recent[MAX_RECENT:]
        self.render_recent()

    def render_recent(self):
        for w in self.recent_box.winfo_children():
            w.destroy()
        if not self.recent:
            tk.Label(self.recent_box, text="Nothing sorted yet.", bg=C["deep"], fg=C["muted"],
                     font=self.fonts.small, anchor="w").pack(fill="x")
            return
        for mark, text in self.recent:
            row = tk.Frame(self.recent_box, bg=C["deep"])
            row.pack(fill="x", pady=1)
            col = {"✓": C["accent"], "–": C["muted"]}.get(mark, C["text"])
            tk.Label(row, text=mark, bg=C["deep"], fg=col, font=self.fonts.body, width=2).pack(side="left")
            tk.Label(row, text=short(text, 64), bg=C["deep"], fg=C["text"] if mark == "✓" else C["muted"],
                     font=self.fonts.small, anchor="w").pack(side="left", fill="x")

    def update_status(self):
        active = self.popup is not None and self.popup.winfo_exists()
        waiting = len(self.jobs)
        if active or waiting:
            self.status.config(text=f"Sorting…  {waiting} more in the queue" if waiting else "Sorting…",
                               fg=C["accent"])
        else:
            self.status.config(text="Ready.  Enter saves · Esc skips · drop more any time.",
                               fg=C["muted"])

    # -- second launch hands its files to this window
    def listen(self, sock):
        def loop():
            while True:
                try:
                    conn, _ = sock.accept()
                    data = b""
                    while chunk := conn.recv(65536):
                        data += chunk
                    conn.close()
                    paths = [p for p in data.decode("utf-8").split("\n") if p]
                    self.call(lambda: (self.raise_window(), paths and self.add_paths(paths)))
                except Exception:
                    logging.exception("listener")
        threading.Thread(target=loop, daemon=True).start()

    def raise_window(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def run_sorter(self, paths):
        if paths:
            self.root.after(300, lambda: self.add_paths(paths))
        self.root.protocol("WM_DELETE_WINDOW", self.root.quit)
        self.check_updates_later()
        self.root.mainloop()


def main():
    migrate_old_name()
    APPDIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=LOG_PATH, level=logging.INFO, format="%(asctime)s %(levelname)s [sorter] %(message)s")
    logging.info("Beat Sorter v%s starting", __version__)
    if sys.platform.startswith("win"):
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    paths = [a for a in sys.argv[1:] if not a.startswith("--")]
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", PORT))
        sock.listen(4)
    except OSError:
        # Already open - pass the dropped files to that window and exit.
        try:
            with socket.create_connection(("127.0.0.1", PORT), timeout=3) as c:
                c.sendall("\n".join(str(Path(p).resolve()) for p in paths).encode("utf-8"))
        except OSError:
            pass
        return
    app = SorterApp()
    app.listen(sock)
    app.run_sorter(paths)


if __name__ == "__main__":
    main()
