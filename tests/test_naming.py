import naming

T = "{name}_{bpm}bpm_{key}_v{version}"


def test_build_stem_basic_and_empty_fields():
    assert naming.build_stem(T, "Nightdrive", 140.0, "Fm", 3) == "Nightdrive_140bpm_Fm_v03"
    assert naming.build_stem(T, "Night/drive?", 92.5, "", 1) == "Nightdrive_92.5bpm_v01"
    assert naming.build_stem(T, "X", "", "C#m", 12) == "X_C#m_v12"
    alt = "{name} - {key} - {bpm} BPM (v{version})"
    assert naming.build_stem(alt, "Wave", "100", "Ab", 2) == "Wave - Ab - 100 BPM (v02)"


def test_parse_stem_roundtrip():
    assert naming.parse_stem(T, "Nightdrive_140bpm_Fm_v03") == {
        "name": "Nightdrive", "bpm": "140", "key": "Fm", "version": "03"}
    assert naming.parse_stem(T, "random thing") is None


def test_clean_project_name():
    assert naming.clean_project_name("Nightdrive_2") == "Nightdrive"
    assert naming.clean_project_name("Nightdrive (autosave)") == "Nightdrive"
    assert naming.clean_project_name("Room 404") == "Room 404"
    # FL auto-names stay whole, even after "save new version"
    assert naming.clean_project_name("Project_23") == "Project_23"
    assert naming.clean_project_name("Project_23_2") == "Project_23"
    assert naming.is_generic("Untitled 4") and not naming.is_generic("drake type")


def test_parse_hints_from_old_file_names():
    h = naming.parse_hints("dark trap 140 bpm Am final (1)", T)
    assert h == {"bpm": "140", "key": "Am", "name": "dark trap"}
    h = naming.parse_hints("Bm melody 150BPM_master", T)
    assert (h["bpm"], h["key"], h["name"]) == ("150", "Bm", "melody")
    assert "key" not in naming.parse_hints("em type beat", T)   # not a key
    assert "key" not in naming.parse_hints("Em type re", T)


def test_next_version_counts_per_beat(tmp_path):
    for f in ["Nightdrive_140bpm_Fm_v01.wav", "Nightdrive_140bpm_Fm_v02.mp3",
              "Nightdrive_150bpm_Gm_v07.wav", "Other_140bpm_Fm_v09.wav"]:
        (tmp_path / f).touch()
    (tmp_path / "Nightdrive_140bpm_Fm_v08_stems").mkdir()
    assert naming.next_version(tmp_path, T, "Nightdrive") == 9
    assert naming.next_version(tmp_path, T, "Other") == 10
    assert naming.next_version(tmp_path, T, "New") == 1


def test_unique_path_never_overwrites(tmp_path):
    p = tmp_path / "a.wav"
    p.touch()
    assert naming.unique_path(p).name == "a (2).wav"


N = naming.DEFAULT_TEMPLATE  # {name}_{bpm}bpm_{key}_{type}_v{version}_{typeversion}


def test_type_and_type_version_in_names():
    assert naming.build_stem(N, "SynthTrap", 120, "Fm", 1, 1, "Master", 1) == "SynthTrap_120bpm_Fm_Master_v1_01"
    assert naming.build_stem(N, "SynthTrap", 120, "Fm", 8, 1, "Master", 1) == "SynthTrap_120bpm_Fm_Master_v8_01"
    hy = "{name}-{bpm}bpm-{key}-{type}-v{version}_{typeversion}"
    assert naming.build_stem(hy, "SynthTrap", 120, "Fm", 8, 1, "Master", 2) == "SynthTrap-120bpm-Fm-Master-v8_02"
    # no type picked: type and its number drop out with their separators
    assert naming.build_stem(N, "SynthTrap", 120, "Fm", 8, 1, "", 3) == "SynthTrap_120bpm_Fm_v8"
    assert naming.parse_stem(N, "SynthTrap_120bpm_Fm_Master_v8_01") == {
        "name": "SynthTrap", "bpm": "120", "key": "Fm", "type": "Master", "version": "8", "typeversion": "01"}


def test_versions_count_all_exports_and_each_type(tmp_path):
    for f in ["SynthTrap_120bpm_Fm_v01.wav", "SynthTrap_120bpm_Fm_v02.mp3",   # older default format
              "SynthTrap_120bpm_Fm_Demo_v3_01.wav", "SynthTrap_120bpm_Fm_Demo_v4_02.wav",
              "SynthTrap_120bpm_Fm_Mix_v5_01.wav", "SynthTrap_120bpm_Fm_v6.wav",
              "SynthTrap_120bpm_Fm_Demo_v7_03.wav", "Other_120bpm_Fm_Master_v9_04.wav"]:
        (tmp_path / f).touch()
    assert naming.next_versions(tmp_path, N, "SynthTrap", "Master") == (8, 1)   # 8th export, 1st Master
    assert naming.next_versions(tmp_path, N, "SynthTrap", "Demo") == (8, 4)
    assert naming.next_versions(tmp_path, N, "SynthTrap", "") == (8, 1)
    assert naming.next_versions(tmp_path, N, "New", "Mix") == (1, 1)
