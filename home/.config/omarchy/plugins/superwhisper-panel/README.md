# Superwhisper panel for Omarchy

A Quickshell bar widget: live dictation status, the last dictation with its
stats, and quick access to processing mode, language, tone, microphone, history
and settings. An on/off switch in the popup's header starts and stops the
service for this session, the way Omarchy's Bluetooth and Tailscale panels
switch theirs; Launch at Login is left to its own setting, and a dictation key
starts the service again. The bar icon dims while it is off.

Built for [Omarchy](https://omarchy.org). MIT licensed.

## What this is, and is not

This is the **panel only**: QML, a little JavaScript, and one Python helper that
reads a status snapshot. It is a client of the Superwhisper daemon, which is a
separate, closed-source product. Everything the panel offers — languages, tones,
processing modes, microphones — is named by the daemon at runtime, so the
panel carries no copy of any of those lists and none of them need changing
here when the product gains one. [PROTOCOL.md](PROTOCOL.md) is the whole contract.

## Requirements

- Omarchy's Quickshell desktop (`omarchy-shell`, the `quattro` line): the panel
  imports its `qs.Commons` and `qs.Ui` modules.
- `python3` for `status.py`, and `wl-copy` for copying a dictation.
- A running Superwhisper daemon for live data, or `tools/fake-daemon.py` for
  development (below).

## Install

The Superwhisper installer links this plugin into `~/.config/omarchy/plugins/`
and enables it, so a normal install needs nothing here.

On Omarchy, the `superwhisper-bin` package links the same directory from
`/opt/superwhisper` when Superwhisper is selected under _Setup > Defaults >
Dictation_.

To work on it, link this directory from a Superwhisper checkout in place of the
installed copy:

```bash
ln -sfn "$PWD/app/assets/omarchy-plugin/superwhisper-panel" ~/.config/omarchy/plugins/superwhisper-panel
omarchy-shell shell rescanPlugins
omarchy plugin enable superwhisper.panel --before omarchy.clock
```

Saving a file under `~/.config/omarchy/plugins/` reloads the plugin, so edits show
up in the bar as you make them. `omarchy plugin disable superwhisper.panel` and
removing the link undoes it.

One plugin per id: only one copy may claim `superwhisper.panel`, so replace the
installer's link rather than adding a second; re-running the installer puts the
shipped copy back.

The plugin id is `superwhisper.panel`. The bar keys its layout and per-widget
settings by that id, and Omarchy reserves the `omarchy.` prefix for first-party
plugins, so this one is namespaced under the product instead. Omarchy names a
plugin's directory after its id; the installer's `superwhisper-panel` predates
that and still works, because the catalog reads the id out of `manifest.json`
wherever it finds it.

## Developing without Superwhisper

You do not need Superwhisper installed, or a licence, to work on the panel. A
fixture daemon serves the same contract:

```bash
python3 tools/fake-daemon.py            # prints SUPERWHISPER_RUNTIME=<dir>
SUPERWHISPER_RUNTIME=<dir> python3 status.py
```

`--phase recording`, `--processing offline_lite`, `--no-last` and `--not-ready`
pose the states the panel renders differently. Point the running bar at the
fixture by exporting the same `SUPERWHISPER_RUNTIME` before starting Quickshell.

## Tests

```bash
python3 tests/status_contract.py
```

It runs `status.py` against the fixture, checks every menu comes back named,
and fails if anything here starts importing from an installed application tree.
It needs only Python.

```bash
python3 tests/qml_logic.py
omarchy plugin validate .
```

`tests/qml_logic.py` loads the real `Panel.qml` offscreen and checks the
decisions it makes on its own — the on/off switch against stale snapshots and
the rows the keyboard walks. It needs `quickshell` and Omarchy's shell modules,
and fails when either is missing. `omarchy plugin validate` is the check the
shell itself runs at load time.

## Settings

The popup's Settings and History rows open Superwhisper's settings window
through the CLI (`superwhisper settings`, or `superwhisper settings history`).
That window is the `superwhisper-settings` application shipped with
Superwhisper, not part of this plugin; it follows the Omarchy theme, keeps one
instance, and comes forward on the tab asked for. Where no window can open, the
CLI falls back to the terminal interface.

## Where this code lives

This directory in superwhisper-linux is the panel's only home. Superwhisper's
release bundle ships it, and Omarchy's `superwhisper-bin` package installs it from
that bundle, so the panel always matches the daemon it was built against.

## Layout

| | |
|---|---|
| `manifest.json` | Plugin id, bar-widget entry point, and the icon-size setting |
| `Panel.qml` | The widget and its popup |
| `Service.qml` | Daemon state, and the actions the popup triggers |
| `Model.js` | Pure formatting: relative times, stats lines, option lookup |
| `status.py` | One snapshot of the daemon's state, from the control socket; the settings window reads the same helper |
| `StatusGlyphs.js`, `SuperwhisperStatus.ttf` | The status glyphs, generated upstream and committed here |
| `PROTOCOL.md` | The daemon contract the panel reads |
| `tools/fake-daemon.py` | A fixture daemon serving that contract |
| `tests/` | The contract test and the offscreen QML harness |

`Panel.qml` imports `qs.Commons` and `qs.Ui`, so it follows the active Omarchy
theme and text size without carrying colours of its own.

## Where it sits

The installer places the widget just left of the clock, the way Omarchy places
its own world clock. In the middle of the bar the panel opens centred under it
and holds the centre still while it is open, like Omarchy's weather and calendar
panels; moved to either end, it opens under the widget. Omarchy's own Dictation
indicator is hidden while the widget is in the bar, so recording does not light
two microphones side by side.
