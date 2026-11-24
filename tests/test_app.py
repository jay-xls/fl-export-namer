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
    monkeypatch.setattr(c, "UPDATE_REPO", "OWNER/daw-export-fixer")
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


def test_app_starts_with_a_theme_that_differs_from_the_stock_look(tmp_path, monkeypatch):
    """Regression (1.4.0): a synced FL theme made the app crash on launch ('no attribute tray')."""
    import tkinter as tk
    import pytest
    import theme
    custom = theme.derive({"accent": "#3399ff"})
    monkeypatch.setattr(theme, "resolve", lambda cfg: (dict(custom), "synced with FL Studio", None))
    try:
        app = c.App()
    except tk.TclError:  # no display available
        pytest.skip("no display")
    try:
        assert c.C["accent"] == "#3399ff"
    finally:
        c.C.clear()
        c.C.update(theme.FL_DEFAULT)
        app.root.destroy()


def test_settings_carry_over_from_the_old_name(tmp_path, monkeypatch):
    """1.5.0 rename: %APPDATA%\\FL Export Namer is copied to %APPDATA%\\DAW Export Fixer once, and kept."""
    old, new = tmp_path / "FL Export Namer", tmp_path / "DAW Export Fixer"
    old.mkdir()
    (old / "config.json").write_text('{"beats_folder": "X"}', encoding="utf-8")
    monkeypatch.setattr(c, "OLD_APPDIR", old)
    monkeypatch.setattr(c, "APPDIR", new)
    c.migrate_old_name()
    assert (new / "config.json").read_text(encoding="utf-8") == '{"beats_folder": "X"}'
    assert (old / "config.json").exists()               # old folder kept as a backup
    (new / "config.json").write_text("{}", encoding="utf-8")
    c.migrate_old_name()                                 # never overwrites the new folder again
    assert (new / "config.json").read_text(encoding="utf-8") == "{}"


def test_old_default_name_format_is_upgraded(monkeypatch, tmp_path):
    import naming
    monkeypatch.setattr(c, "CONFIG_PATH", tmp_path / "config.json")
    c.save_json(c.CONFIG_PATH, {"template": "{name}_{bpm}bpm_{key}_v{version}_{type}", "version_digits": 2})
    cfg = c.load_config()
    assert (cfg["template"], cfg["version_digits"]) == (naming.DEFAULT_TEMPLATE, 1)
    c.save_json(c.CONFIG_PATH, {"template": "{name} - {key} (v{version})", "version_digits": 2})
    cfg = c.load_config()                                   # your own format is left alone
    assert (cfg["template"], cfg["version_digits"]) == ("{name} - {key} (v{version})", 2)


def test_popup_type_picker_names_the_file(tmp_path, monkeypatch):
    """Pick a type in the popup: version counts every export, the type number counts that type."""
    import tkinter as tk
    import pytest
    import theme
    monkeypatch.setattr(c, "CONFIG_PATH", tmp_path / "config.json")
    try:
        app = c.App()
    except tk.TclError:
        pytest.skip("no display")
    try:
        app.cfg.update(beats_folder=str(tmp_path / "beats"), folder_date=False, theme="default")
        beat = tmp_path / "beats" / "SynthTrap"
        beat.mkdir(parents=True)
        for i in range(1, 8):
            (beat / f"SynthTrap_120bpm_Fm_Demo_v{i}_0{i}.wav").touch()
        wav = tmp_path / "SynthTrap.wav"
        wav.write_bytes(b"RIFF")
        job = c.Job(files=[wav], name="SynthTrap", bpm="120", key="Fm")
        p = c.ExportPopup(app, job)
        assert p.v_type.get() == "" and p.targets()[0] == "SynthTrap_120bpm_Fm_v8"   # none until picked
        p.pick_type("Master")
        assert p.targets()[0] == "SynthTrap_120bpm_Fm_Master_v8_01"
        assert "1st Master" in p.ver_hint.cget("text")
        p.pick_type("Demo")
        assert p.targets()[0] == "SynthTrap_120bpm_Fm_Demo_v8_08"
        p.pick_type("Demo")                                   # click again: no type
        assert p.targets()[0] == "SynthTrap_120bpm_Fm_v8"
        p.destroy()
    finally:
        c.C.clear()
        c.C.update(theme.FL_DEFAULT)
        app.root.destroy()
