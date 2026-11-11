#!/usr/bin/env python3
"""The bar widget's own decisions, checked without a compositor or a daemon.

Its on/off switch is wrong silently rather than loudly: a snapshot already on
its way with the old answer can throw the knob back, and the rows the keyboard
walks change with the service. Neither should rest on somebody trying it, so
tests/qml/shell.qml drives the real functions off the real Panel.qml and this
reports what it found.

Needs quickshell and Omarchy's qs.Commons / qs.Ui, which the harness links in.
"""
import os, re, shutil, subprocess, sys, tempfile, threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# CI points this at a pinned checkout of Omarchy's shell/ directory.
SHELL = Path(os.environ.get("OMARCHY_SHELL", "/usr/share/omarchy/shell"))

# A check that cannot run fails: a skip that reads as a pass let QML errors ship.
if shutil.which("quickshell") is None:
    raise SystemExit("quickshell is not installed; the widget's logic cannot be checked")
if not SHELL.is_dir():
    raise SystemExit(f"Omarchy's shell modules are not at {SHELL}; set OMARCHY_SHELL")

# The harness has no way to end its own process — Quickshell does not wire
# Qt.exit — so it is given a moment and then read.
# Offscreen: this checks decisions, not pixels, so it needs no session and runs
# the same on a build machine as it does here.
env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
env.pop("WAYLAND_DISPLAY", None)
env.pop("DISPLAY", None)
# Omarchy sets QT_QPA_PLATFORMTHEME=gtk3, and that theme opens a GTK display of
# its own even under offscreen; with no display it fails and the harness dies
# before printing a check.
env.pop("QT_QPA_PLATFORMTHEME", None)

# Built here rather than committed: `qs.Commons` and `qs.Ui` resolve against the
# config root, and a published checkout must carry no link into /usr/share.
with tempfile.TemporaryDirectory(prefix="superwhisper-qml-") as directory:
    harness = Path(directory)
    shutil.copy(ROOT / "tests/qml/shell.qml", harness / "shell.qml")
    for name in ("Service.qml", "Model.js", "StatusGlyphs.js", "SuperwhisperStatus.ttf"):
        shutil.copy(ROOT / name, harness / name)
    # The bar widget under another name: Panel.qml extends qs.Ui's Panel, and a
    # Panel.qml beside it would resolve that name to itself.
    shutil.copy(ROOT / "Panel.qml", harness / "BarPanel.qml")
    (harness / "Commons").symlink_to(SHELL / "Commons")
    # qs.Ui as Omarchy ships it, but for KeyboardPanel: the bar widget's popup
    # is a layer shell window, which has no backend offscreen, so a plain Item
    # with the same properties takes its place.
    shutil.copytree(SHELL / "Ui", harness / "Ui", symlinks=True)
    shutil.copy(ROOT / "tests/qml/KeyboardPanel.qml", harness / "Ui/KeyboardPanel.qml")
    # Quickshell keeps per-instance state in the runtime directory; a private
    # one also works where the session has none (CI containers).
    runtime = harness / "runtime"
    runtime.mkdir(mode=0o700)
    env["XDG_RUNTIME_DIR"] = str(runtime)
    # Read until the harness prints its tally ("ALL OK" or "N FAILED"), then
    # stop it, rather than waiting out the whole allowance on every run.
    shell = subprocess.Popen(["quickshell", "-p", str(harness)], stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, text=True, env=env)
    timer = threading.Timer(30, shell.kill)
    timer.start()
    lines = []
    for line in shell.stdout:
        lines.append(line)
        if re.search(r"qml:\s+(ALL OK|\d+ FAILED)", re.sub(r"\x1b\[[0-9;]*m", "", line)):
            break
    timer.cancel()
    shell.kill()
    shell.wait()
    output = "".join(lines)

plain = re.sub(r"\x1b\[[0-9;]*m", "", output)
# Quickshell prefixes each line with its own level and category.
checks = re.findall(r"qml:\s+(ok|FAIL)\s+(.*?)\s*$", plain, re.MULTILINE)
failed = [name for state, name in checks if state == "FAIL"]

assert checks, "the harness produced no checks:\n" + plain[-2000:]
# Name what broke before complaining that the run was incomplete: a failed check
# is the useful message, and it is also why the run did not reach "ALL OK".
assert not failed, "failed: " + "; ".join(failed)
assert "ALL OK" in plain, "harness did not finish:\n" + plain[-2000:]

print(f'{{"qml_logic_checks": {len(checks)}, "failed": 0}}')
