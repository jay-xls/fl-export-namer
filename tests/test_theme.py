import theme

# A theme file as FL Studio writes it: UTF-8 BOM, CRLF, colours as signed 32-bit ints.
SAMPLE = ("\ufeffHue=-30\r\nSaturation=-256\r\nLightness=-120\r\nContrast=0\r\nText=0\r\n"
          "Selected=-15654348\r\n"         # 0xFF112234 in RGB order
          "Highlight=-16776961\r\n"          # 0xFF0000FF as COLORREF = pure red
          "TextColor=-1\r\nLightmode=0\r\nBackColor=-16777216\r\n")


def test_colours_decode_in_the_right_byte_order():
    th = theme.parse_flstheme(SAMPLE)
    assert th["highlight"] == "#ff0000"      # COLORREF: red in the low byte
    assert th["selected"] == "#112234"       # RGB order: -0xEEDDCC = 0xFF112234
    assert th["textcolor"] == "#ffffff"
    assert th["hue"] == -30 and th["lightness"] == -120


def test_garbage_is_rejected():
    import pytest
    with pytest.raises(ValueError):
        theme.parse_flstheme("hello\nworld")


def test_untouched_theme_is_fl_default():
    assert theme.palette_from_flstheme(theme.parse_flstheme("Hue=0\nSaturation=0\nLightness=0\n")) == theme.FL_DEFAULT


def test_theme_file_palette():
    pal = theme.palette_from_flstheme(theme.parse_flstheme(SAMPLE))
    assert pal["accent"] == "#ff0000"                     # Highlight is the accent
    r, g, b = theme.to_rgb(pal["bg"])
    assert max(r, g, b) - min(r, g, b) <= 1               # Saturation -256 = grey
    assert theme.luminance(pal["bg"]) < theme.luminance(theme.FL_DEFAULT["bg"])  # Lightness < 0 = darker
    assert theme.contrast(pal["text"], pal["bg"]) >= 4.5


def test_grey_highlight_falls_back_to_selected():
    th = {"highlight": "#f8f6f6", "selected": "#52ff1b"}
    assert theme.pick_accent(th) == "#52ff1b"


def test_derive_keeps_text_readable():
    pal = theme.derive({"bg": "#202020", "text": "#252525", "accent": "#222222"})
    assert theme.contrast(pal["text"], pal["bg"]) >= 4.5
    assert theme.contrast(pal["on_accent"], pal["accent"]) >= 2
    light = theme.derive({"bg": "#e8e8e8", "panel": "#ffffff", "field": "#ffffff", "text": "#202020"})
    assert theme.contrast(light["muted"], light["bg"]) >= 3
    assert set(light) == set(theme.FL_DEFAULT)


def test_resolve_modes(tmp_path, monkeypatch):
    monkeypatch.setattr(theme, "theme_dirs", lambda: [])
    pal, status, src = theme.resolve({"theme": "auto"})
    assert pal == theme.FL_DEFAULT and src is None and "not found" in status
    f = tmp_path / "Mine.flstheme"
    f.write_text(SAMPLE, encoding="utf-8")
    pal, status, src = theme.resolve({"theme": "file", "theme_file": str(f)})
    assert pal["accent"] == "#ff0000" and src == f
    pal, _, _ = theme.resolve({"theme": "custom", "theme_colors": {"accent": "#3399ff"}})
    assert pal["accent"] == "#3399ff" and pal["bg"] == theme.FL_DEFAULT["bg"]
    pal, status, _ = theme.resolve({"theme": "file", "theme_file": str(tmp_path / "gone.flstheme")})
    assert pal == theme.FL_DEFAULT and "couldn't read" in status


def test_auto_finds_fl_current_theme(tmp_path, monkeypatch):
    d = tmp_path / "Documents" / "Image-Line" / "FL Studio" / "Settings" / "Themes"
    d.mkdir(parents=True)
    (d / theme.CURRENT_NAME).write_bytes(SAMPLE.encode("utf-8"))
    monkeypatch.setattr(theme, "documents_dir", lambda: tmp_path / "Documents")
    monkeypatch.setattr(theme.Path, "home", lambda: tmp_path / "nohome")
    monkeypatch.delenv("OneDrive", raising=False)
    assert theme.find_current_theme() == d / theme.CURRENT_NAME
    pal, status, src = theme.resolve({"theme": "auto"})
    assert pal["accent"] == "#ff0000" and "synced" in status


def test_utf16_theme_file(tmp_path):
    f = tmp_path / "t.flstheme"
    f.write_bytes(SAMPLE.encode("utf-16"))
    assert theme.read_flstheme(f)["highlight"] == "#ff0000"


def test_colorref_for_windows():
    assert theme.colorref("#112233") == 0x332211
