# Changelog

Every release gets a section here **before** it's built - the release workflow
uses it as the release notes and refuses to run without one.
Versions: `MAJOR.MINOR.PATCH` - bug fix = patch, new feature = minor.

## [1.5.0] - 2026-11-24
### Changed
- New name: **FL Export Namer is now DAW Export Fixer**, since it works with Ableton Live too. The project lives at github.com/jlnorge/daw-export-fixer and the guide at jlnorge.github.io/daw-export-fixer.
- Upgrading keeps everything: settings and per-project memory are copied from `%APPDATA%\FL Export Namer` (left in place as a backup), "Start with Windows" carries over, and Setup replaces the old install, its Start menu entries and its startup entry.

## [1.4.1] - 2026-11-24
### Fixed
- The app crashed on launch ("'App' object has no attribute 'tray'") when your FL Studio or Ableton theme differs from the stock look.

## [1.4.0] - 2026-11-24
### Added
- Ableton Live support: the app watches your Live projects folder, on its own or alongside the FL Studio one. BPM comes from the set's tempo, key from Live's Scale setting or the set's in-key MIDI clips. If the set has none, both are estimated from the audio, and the audio estimates are always one click away to override Live.
- FL STUDIO / ABLETON tabs in Settings and Beat Sorter. Each program keeps its own watch folder, beats folder, ignore list and theme. "Set as default" picks the tab that opens first.
- Popups come up in the colours of the program the export came from, with the program in the title bar.
- Theme: "Match Ableton" follows Live's current theme. Also: Ableton default, any `.ask` theme file, or custom colours.
- "Check against audio" next to the BPM gets an audio tempo estimate even when the project gave one.
### Changed
- No tempo in the project or file name: BPM is now estimated from the audio instead of left blank.
- Tray: "Open FL Studio beats folder" / "Open Ableton beats folder".

## [1.3.1] - 2026-11-24
### Changed
- The project moved to github.com/jlnorge/fl-export-namer: the update check, download links and the guide (jlnorge.github.io/fl-export-namer) now point there.

## [1.3.0] - 2026-11-24
### Added
- Theme setting: **Match FL Studio** (default) follows FL's current theme automatically, updating when FL closes. Also: FL default, any `.flstheme` file, or Custom.
- Colour editor with a screen eyedropper, so you can pick colours straight off your FL Studio window.
### Changed
- New default look: FL Studio's stock blue-grey and orange, in the app and on the guide. Tray and window icons follow the theme.
- Warnings are shown in red instead of amber, so they stand out from the orange accent.

## [1.2.0] - 2026-11-24
### Added
- Update check: once a day the app looks for a newer release and shows a "download the update" toast. Can be turned off in Settings.
- Project now lives on GitHub: releases are built and self-tested automatically, the guide is published from `docs/`.
### Fixed
- `build.bat` works in folders with `&` in their name, and makes a standard zip that opens on any device.

## [1.1.0] - 2026-11-24
### Added
- Shareable Windows build: installer, no Python needed. Watcher and Beat Sorter in one app.
- "Start with Windows" toggle, version number in Settings, tray -> Open Beat Sorter, log link in Beat Sorter.
### Fixed
- Beat Sorter could show the key in the BPM box.

## [1.0.0] - 2026-11-20
### Added
- Export watcher: BPM read from the .flp, key detected from audio, automatic versions.
- Beat Sorter for old exports (BPM + key estimated from audio, hints from file names).
- Dated beat folders, FL auto-names (`Project_23`) kept whole, undo, skip reasons in the log.
