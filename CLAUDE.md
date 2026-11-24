# DAW Export Fixer - project brief for Claude

Windows tray app for FL Studio and Ableton Live producers (owner: Jay). Watches the FL and/or
Ableton projects folders; when a render lands it shows a popup themed like the program it came
from, with name / BPM / key / version pre-filled, then renames and files the export into that
program's beats folder. Beat Sorter (same app, `--sorter`) does the same for
old exports by estimating BPM + key from the audio. Shared with friends as a PyInstaller build.

## Files
| file | what |
|---|---|
| `namer_core.py` | everything shared: config/state, per-program config (`DAWS`, `daw_cfg`), live palette (`C`), `Job`, `build_job`, `dest_dir`, `ExportWatcher` (one per program), `ExportPopup`, `SettingsWindow`, `ThemeEditor` + `ScreenPicker` (eyedropper), `Toast`, `App` (tray, apply/undo, theme sync), startup toggle, `__version__`, watcher `main()` |
| `theme.py` | `FL_DEFAULT` / `ABLETON_DEFAULT` palettes, `.flstheme` + Ableton `.ask` parsing, `derive()` from 5 seed colours, finding FL's `__current.flstheme` / Live's current theme (via Preferences.cfg), `resolve(cfg)` |
| `sorter_app.py` | Beat Sorter window (`SorterApp(App)`), drag-and-drop, file-name hints, single-instance forwarding (port 47614) |
| `naming.py` | templates, version numbering, name cleanup, `parse_hints`, `is_generic` (Project_23) |
| `flp_reader.py` | minimal .flp parser: tempo (event 156, BPM x1000), title. FL 2026 quirk: event 172 is 1 byte - parse both ways |
| `als_reader.py` | streaming .als (gzip XML) parser: tempo (`MainTrack`/`MasterTrack` Tempo/Manual), key from Live 12 Scale (`InKey`), in-key clip scales, or a non-default set scale |
| `key_detect.py` / `bpm_detect.py` | numpy-only key + tempo estimation |
| `launcher.py` | packaged entry point: default = watcher, `--sorter`, `--selftest` |
| `daw_export_fixer.pyw`, `beat_sorter.pyw` | thin entry points for running from source |
| `build_kit/` | `build.bat` (venv -> PyInstaller -> selftest -> zip -> Inno Setup), `DAWExportFixer.spec`, `installer.iss`, `icon.ico` |
| `docs/` | the user guide (`index.html` + `img/`), published to GitHub Pages on merge to `main` |
| `tests/` | pytest suite (naming, .flp reader, detection, folders, update check) |
| `tools/release_notes.py` | pulls a version's section out of `CHANGELOG.md` for the release page |
| `.github/workflows/` | `ci.yml` (lint + tests + selftest on every PR), `release.yml` (build + publish), `pages.yml` (guide) |
| `requirements.txt` / `requirements-dev.txt` | pinned runtime / build+test dependencies |

## Run / test / build (Windows)
- From source: `py daw_export_fixer.pyw` (watcher), `py beat_sorter.pyw`, `py daw_export_fixer.pyw --demo` (popup with sample data, add `--ableton` for the Ableton one), `py daw_export_fixer.pyw --test "C:\path\render.wav"`.
- Self-test: `py launcher.py --selftest` -> writes `%APPDATA%\DAW Export Fixer\selftest.txt`.
- Tests: `py -m pytest tests` (needs `requirements-dev.txt`).
- Local build: double-click `build_kit\build.bat`. Output in `dist\`. Real releases come from the `release` workflow.
- Settings/state/log: `%APPDATA%\DAW Export Fixer\` (`config.json`, `state.json`, `log.txt`).

## How work flows (GitHub)
- Never commit straight to `main`. Make a branch (`feature/stems-zip`, `fix/bpm-amber`), commit, open a
  pull request. The `checks` workflow must be green before Jay merges.
- Every user-visible change: a line in `CHANGELOG.md` under the next version, and `docs/index.html`
  updated in the same PR.
- Releasing: add the `CHANGELOG.md` section, bump `__version__` (bug fix = patch, feature = minor),
  merge, then run the `release` workflow (Actions tab) or push tag `vX.Y.Z`. It builds on Windows,
  runs the selftest on the built exe, and publishes Setup.exe + zip + SHA256SUMS with notes from
  the changelog. The app's update check reads that release.
- `UPDATE_REPO` in `namer_core.py` must stay the real `owner/repo`.
- Renamed from FL Export Namer in 1.5.0. Keep the installer's `AppId` (upgrades depend on it), and keep
  `migrate_old_name()` (copies `%APPDATA%\FL Export Namer`, moves the startup entry) plus the installer's
  old-name cleanup for a few releases so people upgrading from 1.4.x keep their setup.

## Rules for changes
- Two programs (`DAWS = ("fl", "ableton")`). Per-program settings are listed in `PER_DAW`: FL keeps the
  original key names (`watch_folder`), Ableton's are prefixed (`ableton_watch_folder`). Read them through
  `daw_cfg(cfg, daw)` / `app.dcfg()`, never `cfg["watch_folder"]` directly. `app.set_daw()` swaps `C`.
- Keep the FL look: colours only from `C` (never hard-coded hex - users can re-theme, light themes included;
  text on an accent background is `C["on_accent"]`), widgets `FlatButton` / `flat_entry` / `Toggle` / `Segmented` / `ThemedWindow`.
  New palette keys go in `theme.FL_DEFAULT` and `theme.derive()`. The guide (`docs/`) uses the FL default palette only.
- Never block the Tk thread: detection runs in threads and hands results back with `app.call(...)`.
  Bind values into those lambdas (`lambda r=res: ...`) - a late-binding bug once put the key in the BPM box.
- New config keys go in `DEFAULT_CONFIG` (old configs get the default automatically).
- Never overwrite user files: use `naming.unique_path`; every move must stay undoable.
- New third-party packages must be added to the pip line in `build.bat` and, if PyInstaller misses
  them, to the spec; then add a check to `selftest()` in `launcher.py`.
- Batch files: quote every path (`set "X=..."`) - Jay's folders can contain `&`.
- Defaults must work for friends too: Jay's own folders (`Music\FL Projects`, `Music\FL Export`) are
  used only when they exist.
