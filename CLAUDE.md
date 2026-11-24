# FL Export Namer - project brief for Claude

Windows tray app for FL Studio producers (owner: Jay). Watches the FL projects folder; when a
render lands it shows an FL-themed popup with name / BPM / key / version pre-filled, then renames
and files the export into the beats folder. Beat Sorter (same app, `--sorter`) does the same for
old exports by estimating BPM + key from the audio. Shared with friends as a PyInstaller build.

## Files
| file | what |
|---|---|
| `namer_core.py` | everything shared: config/state, theme (`C`), `Job`, `build_job`, `dest_dir`, `ExportWatcher`, `ExportPopup`, `SettingsWindow`, `Toast`, `App` (tray, apply/undo), startup toggle, `__version__`, watcher `main()` |
| `sorter_app.py` | Beat Sorter window (`SorterApp(App)`), drag-and-drop, file-name hints, single-instance forwarding (port 47614) |
| `naming.py` | templates, version numbering, name cleanup, `parse_hints`, `is_generic` (Project_23) |
| `flp_reader.py` | minimal .flp parser: tempo (event 156, BPM x1000), title. FL 2026 quirk: event 172 is 1 byte - parse both ways |
| `key_detect.py` / `bpm_detect.py` | numpy-only key + tempo estimation |
| `launcher.py` | packaged entry point: default = watcher, `--sorter`, `--selftest` |
| `fl_export_namer.pyw`, `beat_sorter.pyw` | thin entry points for running from source |
| `build_kit/` | `build.bat` (venv -> PyInstaller -> selftest -> zip -> Inno Setup), `FLExportNamer.spec`, `installer.iss`, `icon.ico` |
| `docs/` | the user guide (`index.html` + `img/`), published to GitHub Pages on merge to `main` |
| `tests/` | pytest suite (naming, .flp reader, detection, folders, update check) |
| `tools/release_notes.py` | pulls a version's section out of `CHANGELOG.md` for the release page |
| `.github/workflows/` | `ci.yml` (lint + tests + selftest on every PR), `release.yml` (build + publish), `pages.yml` (guide) |
| `requirements.txt` / `requirements-dev.txt` | pinned runtime / build+test dependencies |

## Run / test / build (Windows)
- From source: `py fl_export_namer.pyw` (watcher), `py beat_sorter.pyw`, `py fl_export_namer.pyw --demo` (popup with sample data), `py fl_export_namer.pyw --test "C:\path\render.wav"`.
- Self-test: `py launcher.py --selftest` -> writes `%APPDATA%\FL Export Namer\selftest.txt`.
- Tests: `py -m pytest tests` (needs `requirements-dev.txt`).
- Local build: double-click `build_kit\build.bat`. Output in `dist\`. Real releases come from the `release` workflow.
- Settings/state/log: `%APPDATA%\FL Export Namer\` (`config.json`, `state.json`, `log.txt`).

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

## Rules for changes
- Keep the FL look: colours in `C`, widgets `FlatButton` / `flat_entry` / `Toggle` / `Segmented` / `ThemedWindow`.
- Never block the Tk thread: detection runs in threads and hands results back with `app.call(...)`.
  Bind values into those lambdas (`lambda r=res: ...`) - a late-binding bug once put the key in the BPM box.
- New config keys go in `DEFAULT_CONFIG` (old configs get the default automatically).
- Never overwrite user files: use `naming.unique_path`; every move must stay undoable.
- New third-party packages must be added to the pip line in `build.bat` and, if PyInstaller misses
  them, to the spec; then add a check to `selftest()` in `launcher.py`.
- Batch files: quote every path (`set "X=..."`) - Jay's folders can contain `&`.
- Defaults must work for friends too: Jay's own folders (`Music\FL Projects`, `Music\FL Export`) are
  used only when they exist.
