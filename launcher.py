"""Entry point for the packaged app.

    DAW Export Fixer.exe            -> watcher (system tray)
    DAW Export Fixer.exe --sorter   -> Beat Sorter window (files/folders can follow)
"""
import sys


def selftest() -> int:
    """Run inside the built exe: proves every bundled piece actually loads."""
    import tempfile
    import traceback
    from pathlib import Path
    import numpy as np
    import namer_core
    out, ok = [f"DAW Export Fixer v{namer_core.__version__} selftest"], True

    def check(name, fn):
        nonlocal ok
        try:
            out.append(f"  OK    {name}: {fn() or ''}")
        except Exception as e:
            ok = False
            out.append(f"  FAIL  {name}: {type(e).__name__}: {e}")
            out.append(traceback.format_exc())

    def dnd():
        from tkinterdnd2 import TkinterDnD
        root = TkinterDnD.Tk()
        root.withdraw()
        v = root.tk.call("package", "require", "tkdnd")
        root.destroy()
        return f"tkdnd {v}"

    def audio():
        import soundfile as sf
        from bpm_detect import estimate_bpm
        from key_detect import detect_key
        sr, bpm = 44100, 120.0
        t = np.arange(int(sr * 16)) / sr
        y = 0.1 * np.sin(2 * np.pi * 220 * t)          # A3 drone
        beat = int(sr * 60 / bpm)
        for i in range(0, len(y) - 4000, beat):         # clicks on every beat
            y[i:i + 4000] += 0.6 * np.exp(-np.arange(4000) / 300) * np.sin(2 * np.pi * 60 * np.arange(4000) / sr)
        p = Path(tempfile.gettempdir()) / "daw_export_fixer_selftest.wav"
        sf.write(p, y, sr)
        b = estimate_bpm(str(p))
        k = detect_key(str(p), bpm=b[0][0] if b else None)
        p.unlink()
        return f"libsndfile {sf.__libsndfile_version__}, bpm {b[0][0] if b else None}, key {k[0][0] if k else None}"

    check("drag and drop", dnd)
    check("audio + detection", audio)
    if sys.platform.startswith("win"):  # Linux/macOS tray backends differ; the app runs without one there
        check("tray icon", lambda: __import__("pystray").Icon.__module__)
    check("folder watching", lambda: __import__("watchdog.observers", fromlist=["Observer"]).Observer.__name__)
    check("project reader", lambda: __import__("flp_reader").read_flp.__name__)

    def ableton():
        import gzip
        from als_reader import read_als
        p = Path(tempfile.gettempdir()) / "daw_export_fixer_selftest.als"
        p.write_bytes(gzip.compress(b'<?xml version="1.0"?><Ableton Creator="Ableton Live 12.1"><LiveSet>'
                                    b'<MainTrack><DeviceChain><Mixer><Tempo><Manual Value="128"/></Tempo></Mixer>'
                                    b'</DeviceChain></MainTrack></LiveSet></Ableton>'))
        info = read_als(p)
        p.unlink()
        if info.tempo != 128:
            raise ValueError(f"read tempo {info.tempo}")
        return f"Live {info.live_version} set, tempo {info.tempo}"
    check("Ableton set reader", ableton)

    def themes():
        import theme
        from PIL import ImageGrab, ImageTk  # eyedropper
        pal, status, _ = theme.resolve({"theme": "auto"})
        apal, astatus, _ = theme.resolve({"theme": "auto", "daw": "ableton"})
        return (f"{status}, accent {pal['accent']}; Ableton: {astatus}, accent {apal['accent']}; "
                f"{ImageGrab.__name__}, {ImageTk.__name__}")
    check("themes + eyedropper", themes)
    namer_core.APPDIR.mkdir(parents=True, exist_ok=True)
    (namer_core.APPDIR / "selftest.txt").write_text("\n".join(out) + "\n" + ("ALL OK" if ok else "FAILED") + "\n",
                                                   encoding="utf-8")
    return 0 if ok else 1


def run():
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    if "--sorter" in sys.argv:
        sys.argv.remove("--sorter")
        from sorter_app import main
    else:
        from namer_core import main
    main()


if __name__ == "__main__":
    run()
