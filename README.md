# FL Export Namer

**Export a beat from FL Studio or Ableton Live, hit Enter, done.** A small Windows app that watches your FL Studio
and/or Ableton projects folders. When you export, it pops up with the name, BPM, key and next version number
already filled in, then renames the file and files it into one tidy beats folder. Comes with
**Beat Sorter** for your back catalogue: drop old, randomly named exports in and it works out the
BPM and key from the audio.

<img src="docs/img/popup.png" width="520" alt="The popup that appears after exporting: name, BPM read from the project, detected key with alternatives, version, and the final file name">

### [⬇ Download the latest version](https://github.com/jlnorge/fl-export-namer/releases/latest) · [📖 User guide](https://jlnorge.github.io/fl-export-namer/)

Windows 10/11 · free · no Python needed. Windows will say the app is from an unknown publisher
(it isn't code-signed) - click **More info → Run anyway**.

## Features
- **BPM straight from the project** - read from the saved `.flp`, not guessed
- **Ableton Live too** - tempo and key (Live's Scale) read from the `.als`; watch FL and Ableton at the same time, each with its own folders and theme
- **Key detection** from the audio, top 3 guesses one click away
- **Automatic versions** - v01, v02, v03… per beat; nothing is ever overwritten
- **Tidy folders** - one folder per beat, dated by its first export (`Nightdrive 24.11.2026`)
- **Remembers** each project's name and key, so re-exports are usually one keypress
- **Stems and multi-format** - WAV + MP3 = one version; stems get their own folder
- **Beat Sorter** - drop old files or whole folders; BPM + key estimated, file-name clues used, junk stripped
- **Safety net** - undo, copy instead of move, skip, pause
- **Your format** - file-name pattern, key style, sharps/flats, folder layout
- **Update notices** - tells you when a new version is out

## Found a bug / got an idea?
[Open an issue](https://github.com/jlnorge/fl-export-namer/issues/new/choose) - attach your log
(tray icon → **Open log**) for bugs.

---

## For the developer

| | |
|---|---|
| Run from source | `py -m pip install -r requirements.txt` then `py fl_export_namer.pyw` (watcher) / `py beat_sorter.pyw` / `py fl_export_namer.pyw --demo` |
| Tests | `py -m pip install -r requirements-dev.txt` then `py -m pytest tests` |
| Local build | double-click `build_kit\build.bat` → `dist\` |
| Release | add a `CHANGELOG.md` section, bump `__version__` in `namer_core.py`, merge to `main`, then **Actions → release → Run workflow** |
| Guide | edit `docs/index.html` - it republishes automatically when merged to `main` |

How the code is laid out, and the rules for changing it: [`CLAUDE.md`](CLAUDE.md).
