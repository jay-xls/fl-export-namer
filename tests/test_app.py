import os
import time

import namer_core as c


def test_dated_folder_is_created_once_and_reused(tmp_path):
    cfg = dict(c.DEFAULT_CONFIG, beats_folder=str(tmp_path))
    first = c.dest_dir(cfg, "Nightdrive", time.mktime((2026, 11, 20, 12, 0, 0, 0, 0, -1)))
    assert first.name == "Nightdrive 20.11.2026"
    first.mkdir()
    later = c.dest_dir(cfg, "nightdrive", time.mktime((2027, 3, 5, 12, 0, 0, 0, 0, -1)))
    assert later == first                                   # v02 next year lands next to v01
    assert c.dest_dir(cfg, "Night").name.startswith("Night ")  # no prefix confusion
    assert c.dest_dir(dict(cfg, folder_date=False), "X").name == "X"


def test_version_compare_is_numeric():
    assert c.version_tuple("v1.10.0") > c.version_tuple("1.9.9")
    assert not c.version_tuple("v1.2.0") > c.version_tuple("1.2.0")


def test_update_check_is_silent_without_a_repo(monkeypatch):
    monkeypatch.setattr(c, "UPDATE_REPO", "OWNER/fl-export-namer")
    assert c.fetch_latest_release() is None


def test_toasts_render_with_folder_and_link(tmp_path):
    """Regression: a variable name clash once broke every 'Saved' toast."""
    import tkinter as tk
    try:
        app = c.App()
    except tk.TclError:  # no display available
        import pytest
        pytest.skip("no display")
    c.Toast(app, "Saved  x.wav", folder=str(tmp_path))
    c.Toast(app, "update", link=("download the update", "https://github.com/x/y/releases/latest"))
    app.root.update()
    app.root.destroy()


def test_theme_follows_the_file_when_fl_rewrites_it(tmp_path):
    import tkinter as tk
    import theme
    try:
        app = c.App()
    except tk.TclError:  # no display available
        import pytest
        pytest.skip("no display")
    f = tmp_path / "__current.flstheme"
    f.write_text("Hue=0\nSaturation=0\nLightness=0\nHighlight=-16776961\n", encoding="utf-8")
    try:
        app.cfg.update(theme="file", theme_file=str(f))
        app.apply_theme()
        assert c.C["accent"] == "#ff0000"
        f.write_text("Hue=0\nSaturation=0\nLightness=0\nHighlight=-16711936\n", encoding="utf-8")  # green
        os.utime(f, (time.time() + 5, time.time() + 5))
        app.watch_theme()                     # sees the change, waits for the file to settle
        assert c.C["accent"] == "#ff0000"
        app.watch_theme()
        assert c.C["accent"] == "#00ff00"
        c.SettingsWindow(app).destroy()       # windows build fine with the new colours
    finally:
        c.C.clear()
        c.C.update(theme.FL_DEFAULT)
        app.root.destroy()
