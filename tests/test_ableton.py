"""Ableton Live support: .als reading, .ask themes, per-program config, jobs and folder ownership."""
import gzip
import os
import time
from types import SimpleNamespace

import pytest

import namer_core as c
import theme
from als_reader import AlsError, read_als


def als(path, body, creator="Ableton Live 12.1.5", master="MainTrack", tempo="92", compress=True):
    xml = (f'<?xml version="1.0" encoding="UTF-8"?>\n<Ableton MajorVersion="5" Creator="{creator}">'
           f'<LiveSet><Tracks/>{body}<{master}><DeviceChain><Mixer>'
           f'<Tempo><LomId Value="0"/><Manual Value="{tempo}"/></Tempo>'
           f'</Mixer></DeviceChain></{master}></LiveSet></Ableton>').encode("utf-8")
    path.write_bytes(gzip.compress(xml) if compress else xml)
    return path


def scale(root, name):
    return f'<ScaleInformation><RootNote Value="{root}"/><Name Value="{name}"/></ScaleInformation>'


def clip(root, name, in_key=True):
    return f'<MidiClip Id="0">{scale(root, name)}<IsInKey Value="{str(in_key).lower()}"/></MidiClip>'


# ------------------------------------------------------------- .als ----
def test_live12_tempo_and_scale(tmp_path):
    info = read_als(als(tmp_path / "a.als", scale(5, "Minor") + '<InKey Value="true"/>'))
    assert (info.tempo, info.tempo_source, info.live_version) == (92.0, "project", "12.1.5")
    assert (info.root, info.minor, info.key_source) == (5, True, "scale")


def test_live11_master_track_uncompressed(tmp_path):
    info = read_als(als(tmp_path / "b.als", "", creator="Ableton Live 11.3.13", master="MasterTrack",
                        tempo="140.5", compress=False))
    assert (info.tempo, info.live_version, info.root) == (140.5, "11.3.13", None)


def test_untouched_c_major_is_not_a_key(tmp_path):
    info = read_als(als(tmp_path / "c.als", scale(0, "Major") + '<InKey Value="false"/>'))
    assert info.root is None  # Live's default - the app estimates from the audio instead


def test_clip_scales_vote_when_scale_mode_is_off(tmp_path):
    body = scale(0, "Major") + '<InKey Value="false"/>' + clip(9, "Minor") + clip(9, "Minor") + clip(2, "Dorian") \
        + clip(4, "Major", in_key=False)
    info = read_als(als(tmp_path / "d.als", body))
    assert (info.root, info.minor, info.key_source) == (9, True, "clips")


def test_non_default_scale_without_scale_mode_and_modes(tmp_path):
    info = read_als(als(tmp_path / "e.als", scale(2, "Dorian")))
    assert (info.root, info.minor, info.scale_name, info.key_source) == (2, True, "Dorian", "set")
    info = read_als(als(tmp_path / "f.als", scale(7, "Whole Tone") + '<InKey Value="true"/>'))
    assert info.root is None  # not a major/minor key


def test_not_a_set(tmp_path):
    p = tmp_path / "x.als"
    p.write_bytes(gzip.compress(b"hello"))
    with pytest.raises(AlsError):
        read_als(p)


# ------------------------------------------------------------- .ask ----
ASK_LIVE11 = """<?xml version="1.0" encoding="UTF-8"?>
<Ableton MajorVersion="5"><SkinManager>
  <ControlForeground><R Value="10"/><G Value="20"/><B Value="30"/><Alpha Value="255"/></ControlForeground>
  <SurfaceBackground><R Value="200"/><G Value="200"/><B Value="200"/><Alpha Value="255"/></SurfaceBackground>
  <ChosenDefault><R Value="0"/><G Value="120"/><B Value="255"/><Alpha Value="255"/></ChosenDefault>
</SkinManager></Ableton>"""
ASK_LIVE12 = """<?xml version="1.0" encoding="UTF-8"?>
<Ableton MajorVersion="6"><Theme><SkinManager>
  <ControlForeground Value="#e0e0e0"/><SurfaceBackground Value="#303030"/>
  <SurfaceHighlight Value="#3c3c3c"/><ControlBackground Value="#1a1a1aff"/><ChosenDefault Value="#ff5500"/>
</SkinManager></Theme></Ableton>"""


def test_ask_both_formats():
    old = theme.parse_ask(ASK_LIVE11)
    assert old["SurfaceBackground"] == "#c8c8c8" and old["ChosenDefault"] == "#0078ff"
    new = theme.parse_ask(ASK_LIVE12)
    assert new["ControlBackground"] == "#1a1a1a"          # alpha dropped
    pal = theme.palette_from_ask(new)
    assert (pal["bg"], pal["accent"], pal["field"]) == ("#303030", "#ff5500", "#1a1a1a")
    light = theme.palette_from_ask(old)                   # light theme stays readable
    assert theme.contrast(light["text"], light["bg"]) >= 4.5 and set(light) == set(theme.FL_DEFAULT)
    with pytest.raises(ValueError):
        theme.parse_ask("<Ableton/>")


def test_match_ableton_finds_the_theme_live_uses(tmp_path, monkeypatch):
    themes = tmp_path / "Themes"
    themes.mkdir()
    (themes / "Default Dark Neutral.ask").write_text(ASK_LIVE11, encoding="utf-8")
    (themes / "Default Dark Neutral Medium.ask").write_text(ASK_LIVE12, encoding="utf-8")
    prefs = tmp_path / "Preferences.cfg"
    prefs.write_bytes(b"\x00junk" + "Default Dark Neutral Medium".encode("utf-16-le") + b"\x00\x01")
    monkeypatch.setattr(theme, "ableton_pref_files", lambda: [prefs])
    monkeypatch.setattr(theme, "ableton_theme_dirs", lambda: [themes])
    pal, status, src = theme.resolve({"daw": "ableton", "theme": "auto"})
    assert pal["accent"] == "#ff5500" and "Medium" in status and src == prefs
    assert theme.auto_source("ableton") == prefs
    monkeypatch.setattr(theme, "ableton_pref_files", lambda: [])
    pal, status, _ = theme.resolve({"daw": "ableton", "theme": "auto"})
    assert pal == theme.ABLETON_DEFAULT and "not found" in status
    assert theme.resolve({"daw": "ableton", "theme": "default"})[0] != theme.FL_DEFAULT


# ------------------------------------------------------ config + jobs ----
def test_each_program_keeps_its_own_folders_and_theme():
    cfg = dict(c.DEFAULT_CONFIG, watch_folder="F:/fl", beats_folder="F:/fl out",
               ableton_watch_folder="A:/live", ableton_beats_folder="A:/live out", ableton_theme="default")
    fl, ab = c.daw_cfg(cfg, "fl"), c.daw_cfg(cfg, "ableton")
    assert (fl["watch_folder"], fl["beats_folder"], fl["theme"], fl["daw"]) == ("F:/fl", "F:/fl out", "auto", "fl")
    assert (ab["watch_folder"], ab["beats_folder"], ab["theme"], ab["daw"]) == (
        "A:/live", "A:/live out", "default", "ableton")
    assert ab["template"] == fl["template"]               # naming is shared
    assert c.daw_key("ableton", "template") == "template"


def test_ableton_job_reads_tempo_and_key_and_keeps_your_override(tmp_path):
    proj = tmp_path / "Live" / "Nightdrive Project"
    proj.mkdir(parents=True)
    als(proj / "Nightdrive.als", scale(5, "Minor") + '<InKey Value="true"/>', tempo="92")
    wav = proj / "Nightdrive.wav"
    wav.write_bytes(b"RIFF")
    os.utime(proj / "Nightdrive.als", (time.time() - 5, time.time() - 5))
    cfg = c.daw_cfg(dict(c.DEFAULT_CONFIG, ableton_watch_folder=str(tmp_path / "Live")), "ableton")
    job = c.build_job([wav], cfg, {"projects": {}})
    assert (job.daw, job.name, job.bpm, job.key, job.bpm_trusted) == ("ableton", "Nightdrive", "92", "Fm", True)
    assert not job.detect_bpm and "Live's Scale" in job.key_source
    # you changed the key in the popup last time: that sticks while Live still says Fm ...
    state = {"projects": {job.project_key: {"name": "Nightdrive", "key": "Ab", "als_key": "Fm"}}}
    assert c.build_job([wav], cfg, state).key == "Ab"
    # ... but a new scale set in Live wins
    state["projects"][job.project_key]["als_key"] = "Cm"
    assert c.build_job([wav], cfg, state).key == "Fm"


def test_export_without_a_set_falls_back_to_the_audio(tmp_path):
    out = tmp_path / "Exports"
    out.mkdir()
    wav = out / "loose idea.wav"
    wav.write_bytes(b"RIFF")
    job = c.build_job([wav], c.daw_cfg(dict(c.DEFAULT_CONFIG, ableton_watch_folder=str(tmp_path)), "ableton"),
                      {"projects": {}})
    assert job.project is None and job.detect_bpm and job.bpm == "" and job.detect_file == wav
    assert ".als" in job.warnings[0]


def test_set_exported_elsewhere_is_found_in_its_project_folder(tmp_path):
    proj = tmp_path / "Nightdrive Project"
    proj.mkdir()
    als(proj / "Nightdrive.als", "", tempo="101")
    (tmp_path / "Renders").mkdir()
    wav = tmp_path / "Renders" / "Nightdrive.wav"
    wav.write_bytes(b"RIFF")
    job = c.build_job([wav], c.daw_cfg(dict(c.DEFAULT_CONFIG, ableton_watch_folder=str(tmp_path)), "ableton"),
                      {"projects": {}})
    assert job.bpm == "101"


def _watchers(cfg):
    app = SimpleNamespace(cfg=cfg, state={}, own_outputs=set())
    return c.ExportWatcher(app, "fl"), c.ExportWatcher(app, "ableton")


def test_overlapping_watch_folders_each_export_goes_to_one_program(tmp_path):
    music = tmp_path / "Music"
    (music / "Beat Project").mkdir(parents=True)
    (music / "Beat Project" / "Beat.als").write_bytes(b"")
    (music / "FL" / "Song").mkdir(parents=True)
    (music / "FL" / "Song" / "Song.flp").write_bytes(b"")
    cfg = dict(c.DEFAULT_CONFIG, watch_folder=str(music), ableton_watch_folder=str(music), watch_ableton=True,
               beats_folder=str(tmp_path / "out1"), ableton_beats_folder=str(tmp_path / "out2"))
    fl, ab = _watchers(cfg)
    live_wav, fl_wav = music / "Beat Project" / "Beat.wav", music / "FL" / "Song" / "Song.wav"
    assert ab.ignored(live_wav) == "" and fl.ignored(live_wav).startswith("looks like")
    assert fl.ignored(fl_wav) == "" and ab.ignored(fl_wav).startswith("looks like")
    # a more specific Ableton folder inside the FL one owns everything under it
    cfg["ableton_watch_folder"] = str(music / "Beat Project")
    assert fl.ignored(live_wav).startswith("inside the Ableton")
    assert ab.ignored(live_wav) == ""
    # nothing is taken from FL while the Ableton side is switched off
    cfg["watch_ableton"] = False
    assert fl.ignored(live_wav) == ""
    # neither program picks up files already in either beats folder
    assert ab.ignored(tmp_path / "out1" / "x.wav") == "already in Beats folder"


def test_settings_tabs_and_ableton_popup(tmp_path, monkeypatch):
    import tkinter as tk
    monkeypatch.setattr(c, "CONFIG_PATH", tmp_path / "config.json")
    try:
        app = c.App()
    except tk.TclError:  # no display available
        pytest.skip("no display")
    try:
        app.cfg.update(theme="default", ableton_theme="default", default_daw="fl")
        app.apply_theme(daw="fl")
        w = c.SettingsWindow(app)
        assert w.daw == "fl" and c.C == theme.FL_DEFAULT
        w.v_watch.set(str(tmp_path / "fl projects"))
        w.switch("ableton")                                  # unsaved FL edit survives the switch
        w2 = [x for x in app.root.winfo_children() if isinstance(x, c.SettingsWindow)][-1]
        assert w2.daw == "ableton" and c.C == theme.ABLETON_DEFAULT
        w2.v_beats.set(str(tmp_path / "live out"))
        w2.set_default()
        w2.save()
        assert app.cfg["watch_folder"] == str(tmp_path / "fl projects")
        assert app.cfg["ableton_beats_folder"] == str(tmp_path / "live out")
        assert app.cfg["default_daw"] == "ableton"
        assert app.daw == "fl" and c.C == theme.FL_DEFAULT  # back to what was showing before
        app.demo("ableton")
        assert app.daw == "ableton" and "Ableton" in app.popup.cfg["daw"].title()
        app.popup.destroy()
        app.root.update()
    finally:
        c.C.clear()
        c.C.update(theme.FL_DEFAULT)
        app.root.destroy()
