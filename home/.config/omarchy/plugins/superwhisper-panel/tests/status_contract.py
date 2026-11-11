#!/usr/bin/env python3
"""status.py against the fixture daemon: the contract the panel reads, with no install.

Runs standalone. If this passes, a contributor can develop the panel without
Superwhisper, and the panel holds no copy of any list the daemon owns.
"""
import json, os, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


# The panel is Omarchy's, so the contract is pinned to a Hyprland session;
# desktop=... checks what another desktop is offered.
HYPRLAND = {"XDG_CURRENT_DESKTOP": "Hyprland"}
KDE = {"XDG_CURRENT_DESKTOP": "KDE", "HYPRLAND_INSTANCE_SIGNATURE": ""}


def snapshot(*flags, runtime=None, desktop=HYPRLAND, helper=(), env=None):
  if runtime:
    flags = (*flags, "--runtime", str(runtime))
  daemon = subprocess.Popen([sys.executable, str(ROOT / "tools/fake-daemon.py"), *flags],
                            stdout=subprocess.PIPE, text=True)
  try:
    runtime = daemon.stdout.readline().strip().split("=", 1)[1]
    deadline = time.monotonic() + 5
    while not (Path(runtime) / "control.sock").exists():
      assert time.monotonic() < deadline, "fixture daemon never opened its socket"
      time.sleep(.02)
    out = subprocess.run([sys.executable, str(ROOT / "status.py"), *helper], capture_output=True, text=True,
                         env=dict(os.environ, SUPERWHISPER_RUNTIME=runtime, **desktop, **(env or {})), timeout=20)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)
  finally:
    daemon.terminate()
    daemon.wait(timeout=5)


def rows_of(*flags, desktop=HYPRLAND):
    out = {}
    for group in snapshot(*flags, desktop=desktop)["configuration"]:
        for row in group["rows"]:
            out[row["key"]] = row
    return out

# The panel imports nothing from the application tree: that reach-out is what kept
# this directory from being a repository of its own.
source = (ROOT / "status.py").read_text()
assert "tray_menu" not in source, "status.py must not import the application's tray menu"
assert "sys.path" not in source, "status.py must not extend sys.path into the application tree"
assert "parents[3]" not in source, "status.py must not address the installed tree by depth"

# The QML cannot be driven from here, so its half of the same rule is read
# statically: every systemctl call and every command must go through the values
# the helper reported, never a literal unit or wrapper path.
service = (ROOT / "Service.qml").read_text()
for number, line in enumerate(service.splitlines(), 1):
    # The one exception is the program's own name, which the QML harness swaps
    # for a stand-in.
    if "systemctl" in line and 'property string serviceControl: "systemctl"' not in line:
        assert "serviceUnit" in line, f"Service.qml:{number} hardcodes a unit: {line.strip()}"
    if "execDetached" in line and "/.local/bin/" in line:
        assert False, f"Service.qml:{number} hardcodes a wrapper path: {line.strip()}"

s = snapshot("--phase", "recording")
assert s["ok"] and s["running"] and s["ready"], s
assert s["phase"] == "recording", s
assert s["processing"] == "offline", s

# Every menu is named by the daemon, never rebuilt here.
for key in ("processingOptions", "languages", "tones", "microphones"):
  assert s[key], f"{key} came back empty"
  for row in s[key]:
    assert set(row) == {"value", "label"} and row["label"], row
assert [r["value"] for r in s["processingOptions"]] == ["cloud", "offline", "offline_lite"], s
assert s["tone"] == "semi-formal" and any(r["value"] == "casual" for r in s["tones"]), s

# A disconnected device is not offered, and the default sits at the top,
# naming the device it records from: stepping onto it in Settings draws that
# label at once, and the row's final text must not be wider than it.
assert s["microphones"][0] == {"value": "", "label": "System default · Built-in Audio"}, s
assert not any(r["label"] == "Unplugged" for r in s["microphones"]), s
assert s["microphone"] == "alsa_input.usb-Fixture", s

# The configured language is named even when this mode cannot use it, so the panel
# can say so rather than showing a bare code.
assert s["language"] == "el" and s["languageLabel"] == "Greek", s
assert not any(r["value"] == "el" for r in snapshot("--processing", "offline_lite")["languages"])

# The panel must act on the install it is reading. A development service owns a
# different socket, wrapper and unit; sending an action to the release wrapper
# instead fails with a bare "No such file or directory (os error 2)" from a
# binary that was never started.
import tempfile
with tempfile.TemporaryDirectory() as parent:
  home = Path(parent) / "home"
  (home / ".local/bin").mkdir(parents=True)
  for name in ("superwhisper", "superwhisper-dev"):
    (home / ".local/bin" / name).touch()
  linked = {"HOME": str(home)}
  dev = Path(parent) / "superwhisper-dev"
  d = snapshot(runtime=dev, env=linked)
  assert d["cli"] == str(home / ".local/bin/superwhisper-dev"), d["cli"]
  assert d["serviceUnit"] == "superwhisper-dev.service", d
  release = Path(parent) / "superwhisper"
  r = snapshot(runtime=release, env=linked)
  assert r["cli"] == str(home / ".local/bin/superwhisper"), r["cli"]
  assert r["serviceUnit"] == "superwhisper.service", r
  # Omarchy's package installs /usr/bin/superwhisper; the ~/.local/bin link
  # comes only from its per-user setup, which fresh installs skipped
  # (omacom/omarchy#15551). The panel must still name a command that exists.
  packaged = Path(parent) / "usr/bin"
  packaged.mkdir(parents=True)
  (packaged / "superwhisper").write_text("#!/bin/sh\n")
  (packaged / "superwhisper").chmod(0o755)
  bare = Path(parent) / "bare"
  bare.mkdir()
  unlinked = {"HOME": str(bare), "PATH": f"{packaged}:{os.environ['PATH']}"}
  p = snapshot(runtime=release, env=unlinked)
  assert p["cli"] == str(packaged / "superwhisper"), p["cli"]
  idle = json.loads(subprocess.run([sys.executable, str(ROOT / "status.py")], capture_output=True, text=True,
                                   timeout=20, env=dict(os.environ, SUPERWHISPER_RUNTIME="/nonexistent",
                                                        **unlinked)).stdout)
  assert idle["cli"] == str(packaged / "superwhisper"), idle["cli"]

# The configuration screen: the window renders whatever arrives here, so the
# shape is the contract rather than any individual setting.
screen = s["configuration"]
assert [g["group"] for g in screen] == ["General", "Vocabulary", "Sound", "Keyboard shortcuts",
                                        "Application", "History"], screen
assert [r["key"] for r in screen[0]["rows"]] == ["language", "tone", "processing",
                                                 "indicator"], screen[0]
assert [r["key"] for r in screen[1]["rows"]] == ["autoVocabulary", "agentVocabulary"], screen[1]
seen = {}
for group in screen:
    assert group["rows"], group
    for row in group["rows"]:
        assert set(row) - {"requires", "also", "optionHelp", "info"} == {"key", "label", "kind", "action", "control",
                                                   "value", "display", "options", "set",
                                                   "help"}, row
        assert row["control"] in ("scale", "segmented", "switch", "slider",
                                  "picker", "cycle", "text"), row
        assert row["label"] and row["help"], row
        assert row["kind"] in ("choice", "switch", "slider", "text"), row
        # A level with no device to set draws as text rather than a slider that
        # would write nowhere, and says why: the display names the missing
        # thing and the explanation carries the daemon's own sentence, which
        # is the one that says what to do about it.
        if row["kind"] == "slider" and not row["set"]:
            assert row["control"] == "text", row
            assert row["display"] and row["display"] != f"{row['value']}%", row
            assert row["help"] and "selected microphone" not in row["help"], row
        # A switch is exactly two states, so the window can draw one.
        if row["kind"] == "switch":
            assert [o["value"] for o in row["options"]] == ["true", "false"], row
        # A row that offers choices must be able to apply one, and a row that
        # cannot be applied must not pretend to offer any. A slider carries a
        # range rather than a list, so it has commands and no options.
        if row["kind"] in ("choice", "switch"):
            assert bool(row["options"]) == bool(row["set"]), row
        else:
            assert not row["options"], row
        for option in row["options"]:
            # Processing modes also say what choosing them would download.
            extra = {"download", "downloadLabel"} if row["key"] == "processing" else set()
            assert {"value", "label"} <= set(option) <= {"value", "label"} | extra \
                and option["label"], option
        seen[row["key"]] = row
assert len(seen) == 19, sorted(seen)

# Rules between rows travel as data, so the window applies them without knowing
# any setting by name: a dependent row names the row and value it needs, and a
# choice names the rows it changes along with itself, by keys that exist.
for row in seen.values():
    if "requires" in row:
        assert set(row["requires"]) == {"key", "value"}, row
        assert row["requires"]["key"] in seen, row
    for value, others in (row.get("also") or {}).items():
        assert value in [o["value"] for o in row["options"]], row
        assert all(key in seen for key in others), row
assert seen["saveRecordings"]["requires"] == {"key": "saveHistory", "value": "true"}
assert seen["retention"]["requires"] == {"key": "saveHistory", "value": "true"}
assert seen["saveHistory"]["also"] == {"false": {"saveRecordings": "false"}}
# The daemon refuses history off while recordings are kept, so recordings go first.
assert seen["saveHistory"]["set"][0] == ["general", "set", "linux.saveRecordingAudio", "false"]
# Only shortcuts the daemon would accept are offered: no chord another action
# uses, and no Disabled where it would leave nothing to start recording with.
for name in ("hold", "toggle"):
    offered = {o["value"] for o in seen[name]["options"]}
    for other in ("hold", "toggle"):
        if other != name and seen[other]["value"]:
            assert seen[other]["value"] not in offered, (name, other, offered)
# The cancel shortcut is set from the CLI only; Settings offers no row for it.
assert "cancel" not in seen, seen.get("cancel")

# Processing carries the one action its models currently need. The panel holds no
# copy of which mode needs what: the daemon reports it and this turns it into a
# command. Cloud needs none; an offline mode offers Download or Delete.
# Cloud runs nothing locally, so it offers nothing to download or delete.
assert rows_of("--processing", "cloud")["processing"]["action"] is None
# An offline mode with its models present offers to remove them, and asks first.
offline = rows_of("--processing", "offline")
assert offline["processing"]["action"]["label"] == "Delete", offline["processing"]
assert offline["processing"]["action"]["confirm"], "deleting models must ask first"
# One request that unloads before deleting, not a file-by-file removal under
# workers that still hold the models.
# Deleting moves off the mode first: here Offline Lite still lacks its model,
# so to Cloud, and only Offline's own models are removed.
assert offline["processing"]["action"]["commands"] == [
    ["models", "select", "cloud"],
    ["models", "remove-offline", "--confirm", "--mode", "offline"]], offline["processing"]["action"]
assert "switch to Cloud" in offline["processing"]["action"]["confirm"], offline["processing"]["action"]

action = rows_of("--processing", "offline", "--models-missing")["processing"]["action"]
assert action["label"] == "Download" and not action["confirm"], action
assert action["commands"] == [["models", "prepare"]], action  # queues every missing model

# Downloading, the row shows how far along it is and offers no second Download.
downloading = rows_of("--processing", "offline", "--models-missing", "--downloading")["processing"]
progress = dict(downloading["progress"])
models_progress = progress.pop("models")
assert progress == {"fraction": 0.25, "label": "Downloading 25%"}, downloading
# Per model, so the window can keep measuring against what was missing at the
# start: a finished model counts as whole rather than dropping out.
assert models_progress == [
    {"id": "transcription", "ready": False, "done": 500_000_000, "total": 2_000_000_000},
    {"id": "vocabulary", "ready": True, "done": 400_000_000, "total": 400_000_000}], models_progress
assert downloading["action"] is None, downloading

# An off-ladder retention still reads as a period, and reads singular at one.
assert seen["retention"]["display"] == "2 weeks", seen["retention"]
labels = [o["label"] for o in seen["retention"]["options"]]
assert "1 week" in labels and "1 weeks" not in labels, labels

# Read-only rows show a value and offer nothing; the shortcut rows are these.
# The control each row is drawn with is the helper's call, not the window's.
assert seen["launchAtLogin"]["control"] == "switch", seen["launchAtLogin"]
assert seen["tone"]["control"] == "scale", seen["tone"]
assert seen["processing"]["control"] == "segmented", seen["processing"]
assert seen["indicator"]["control"] == "segmented", seen["indicator"]
# A short list steps; a catalogue is searched rather than stepped, because every
# step writes and 103 of them is not a way to choose a language.
assert seen["playback"]["control"] == "cycle", seen["playback"]
cloud_language = rows_of("--processing", "cloud")["language"]
assert len(cloud_language["options"]) > 10, cloud_language
assert cloud_language["control"] == "picker", cloud_language
# Pill is one of the three the indicator offers.
assert [o["label"] for o in seen["indicator"]["options"]] == ["Edge glow", "Pill", "Off"]
# Elsewhere the glow is drawn as the pill, so only Pill and Off are offered,
# and a saved glow reads as the pill; shortcuts offer chords the portal takes.
kde = rows_of(desktop=KDE)
assert [o["label"] for o in kde["indicator"]["options"]] == ["Pill", "Off"], kde["indicator"]
assert kde["indicator"]["value"] in ("pill", "off"), kde["indicator"]
assert all("Right" not in o["label"] for o in kde["toggle"]["options"]), kde["toggle"]
# Cancel has a row there (Escape while recording, Shift+Escape otherwise); Hyprland keeps Escape unlisted.
assert [o["label"] for o in kde["cancel"]["options"]][:2] == ["Escape", "Shift+Escape"], kde["cancel"]
assert "F9" in [o["label"] for o in kde["hold"]["options"]], kde["hold"]
assert "cancel" not in rows_of(), "Hyprland lists no cancel row"
# A side mouse button has its own row beside push to talk, on Hyprland only.
assert [o["value"] for o in seen["mouse"]["options"]][:2] == ["Mouse4", "Mouse5"], seen["mouse"]
assert seen["mouse"]["set"] == [["shortcuts", "set", "mouse", "%chord"]], seen["mouse"]
assert "mouse" not in kde, "Only Hyprland binds a mouse button"
# Send is a shortcut, off until set, offering Space first, Hyprland only, and
# explains itself on hover (info).
assert seen["send"]["value"] == "" and seen["send"]["options"][0]["value"] == "Space", seen["send"]
assert seen["send"]["set"] == [["shortcuts", "set", "send", "%chord"]], seen["send"]
assert seen["send"]["info"], seen["send"]
assert "send" not in kde, "Only Hyprland's key hook sees a key during the hold"
# A shortcut offers the common chords, whatever is set now, Disabled, and the
# one option that records instead of applying.
for key in ("hold", "toggle"):
    labels = [o["label"] for o in seen[key]["options"]]
    assert labels[-2:] == ["Disabled", "Record shortcut (Enter)"], seen[key]
    assert seen[key]["value"] in [o["value"] for o in seen[key]["options"]], seen[key]
    assert seen[key]["set"] == [["shortcuts", "set", key, "%chord"]], seen[key]
assert "RightAlt" in [o["value"] for o in seen["hold"]["options"]], seen["hold"]
assert "DoubleTap" in [o["value"] for o in seen["toggle"]["options"]], seen["toggle"]
assert "DoubleTap" not in [o["value"] for o in kde["toggle"]["options"]], "Only Hyprland reports the taps"
# A level is dragged, and the style it writes has to be JSON or `audio set`
# refuses it with "expected value at line 1 column 1".
assert seen["effectVolume"]["control"] == "slider", seen["effectVolume"]
assert ["audio", "set", "soundEffectVolume", "%unit"] in seen["effectVolume"]["set"]
assert ["audio", "set", "recordingIndicatorStyle", "%stylejson"] in seen["indicator"]["set"]
assert seen["hold"]["display"] == "RightAlt", seen["hold"]

# The recording indicator needs two commands, and every placeholder a command
# carries has to be one the settings window knows how to expand: its encode()
# in app/settings/src/contract.rs spells each one out, and passes %s and %n,
# which stand for the value itself, through unchanged.
assert len(seen["indicator"]["set"]) == 2, seen["indicator"]
known = {"%s", "%n", "%j", "%onoff", "%notoff", "%stylejson", "%pct", "%unit",
         "%louder", "%chord"}
window = (ROOT.parents[2] / "settings/src/contract.rs").read_text()
for row in seen.values():
    for argv in row["set"]:
        for part in argv:
            if str(part).startswith("%"):
                assert part in known, f"{row['key']} uses unknown placeholder {part}"
                assert part in ("%s", "%n") or f'"{part}"' in window, \
                    f"the settings window cannot expand {part}"

# History, vocabulary and account: the other three tabs, each already ordered
# and named by the helper so the window only draws what arrives.
# Choosing a mode that lacks its models offers to download them, at their size.
processing = next(r for g in screen for r in g["rows"] if r["key"] == "processing")
lite = next(o for o in processing["options"] if o["value"] == "offline_lite")
assert lite["download"] == [["models", "prepare"]], lite
assert lite["downloadLabel"] == "680 MB", lite
cloud = next(o for o in processing["options"] if o["value"] == "cloud")
assert cloud["download"] == [] and cloud["downloadLabel"] == "", cloud

# Each tone step carries what it does, for the note beside the scale.
tone = next(r for g in screen for r in g["rows"] if r["key"] == "tone")
assert set(tone["optionHelp"]) == {o["value"] for o in tone["options"]}, tone

dictation = s["history"][0]
# The footer counts every dictation, not only the ones the list carries.
assert s["historyTotal"] >= len(s["history"]), s["historyTotal"]
# The first page is 200, not the 50 history_list sends unasked, and nothing is
# left to ask for when it holds them all.
long = snapshot("--older-dictations", "59")
assert (len(long["history"]), long["historyTotal"]) == (60, 60), long["historyTotal"]
assert long["historyMore"] is False, long["historyMore"]
# Past the first page: more is offered, starting after the oldest it holds,
# and the pages after it reach the last dictation with none repeated.
deep = snapshot("--older-dictations", "449")
assert (len(deep["history"]), deep["historyTotal"], deep["historyMore"]) == (200, 450, True), deep["historyTotal"]
assert deep["historyCursor"] == str(deep["history"][-1]["timestamp"]), deep["historyCursor"]
seen = [str(row["timestamp"]) for row in deep["history"]]
cursor = deep["historyCursor"]
for _ in range(5):
  page = snapshot("--older-dictations", "449", helper=("--history-before", cursor))
  assert page["ok"] and page["historyTotal"] == 450, page
  assert all(int(row["timestamp"]) < int(cursor) for row in page["history"]), page["history"][:1]
  seen += [str(row["timestamp"]) for row in page["history"]]
  if not page["historyMore"]:
    break
  cursor = page["historyCursor"]
assert len(seen) == len(set(seen)) == 450, len(seen)
assert seen == sorted(seen, key=int, reverse=True)
by_offset = snapshot("--older-dictations", "449", helper=("--history-offset", "400"))
assert [str(r["timestamp"]) for r in by_offset["history"]] == seen[400:], by_offset["history"][:1]
assert by_offset["historyMore"] is False, by_offset
# A daemon released before paging answers every request with its newest 50:
# those are shown, the total still counts them all, and no next page is
# offered that would only bring the same 50 back. One released before the
# total is counted from general_get's count of the archive.
unpaged = snapshot("--older-dictations", "59", "--no-history-paging")
assert (len(unpaged["history"]), unpaged["historyTotal"]) == (50, 60), unpaged["historyTotal"]
assert unpaged["historyMore"] is False, unpaged
page = snapshot("--older-dictations", "59", "--no-history-paging",
                helper=("--history-before", unpaged["historyCursor"]))
assert page["historyMore"] is False, page
older = snapshot("--older-dictations", "59", "--no-history-total")
assert (len(older["history"]), older["historyTotal"]) == (50, 60), older["historyTotal"]
assert older["historyMore"] is False, older
sys.path.insert(0, str(ROOT))
from status import history_total
listed = {"items": [{}] * 50}
# An empty history is counted as empty, not as the list's length.
assert history_total({"items": [], "total": 0}, {"history": {"entries": 9}}) == 0
# A daemon with neither count is left with what it listed.
assert history_total(listed, {}) == 50
assert set(dictation) == {"text", "truncated", "words", "timestamp", "folder", "createdAt",
                          "duration", "model", "languageModel", "delivery",
                          "device", "audio", "durationMs", "failed", "error"}, dictation
# Playback needs to know whether there is a recording and how long it runs.
assert dictation["audio"] is True and dictation["durationMs"] == 4112, dictation
assert dictation["failed"] is False and dictation["error"] == "", dictation
# A failed dictation is listed, as a failure with its error, where a
# dictation that only heard nothing still is not.
failing = snapshot("--failed-dictation")
failure, completed = failing["history"][:2]
assert failure["failed"] is True and failure["text"] == "", failure
assert failure["error"] == "Cloud transcription failed: HTTP 502", failure
assert failure["duration"] == "45m 0s" and failure["words"] == 0, failure
assert failure["timestamp"] and failure["folder"], failure
assert completed["failed"] is False and completed["text"], completed
assert len(failing["history"]) == len(s["history"]) + 1, failing["history"]
assert failing["historyTotal"] == s["historyTotal"] + 2, failing["historyTotal"]
# `history delete` addresses a dictation by timestamp, so one must always arrive.
assert dictation["timestamp"], dictation
assert dictation["words"] == 8 and dictation["duration"] == "4.1s", dictation
# A wire value is never shown to a person, and a node name is not an identity.
assert dictation["delivery"] == "Pasted", dictation
assert dictation["device"] == "Fixture Microphone", dictation

# A pronunciation belongs to its word rather than standing beside it, which is
# how the terminal interface both lists and edits them.
kinds = [row["kind"] for row in s["vocabulary"]]
assert kinds == ["Word", "Word", "Replacement"], s["vocabulary"]
assert s["vocabulary"][0] == {"kind": "Word", "primary": "Omarchy",
                              "secondary": "Oh Machi, Omachi"}, s["vocabulary"]
assert s["vocabulary"][1]["secondary"] == "", s["vocabulary"]

account = s["account"]
assert account["usedLabel"] == "66" and account["limitLabel"] == "10,000", account
assert account["remainingLabel"] == "9,934", account
assert account["plan"] == "Free" and account["licensed"] is False, account
# The gauge fills by the share used and says it in the terminal's words.
assert abs(account["usageFraction"] - 66 / 10000) < 1e-9, account
assert account["usageLabel"] == "66 / 10,000 words · 9,934 remaining", account
assert account["usageShortLabel"] == "66 / 10,000 · 9,934 left", account

last = s["last"]
assert last["words"] == 8 and last["audioSeconds"] == 4.1, last

idle = snapshot("--no-last", "--not-ready")
assert idle["last"] is None and idle["ready"] is False, idle

# No daemon at all is a state the panel renders, not an error it crashes on.
down = json.loads(subprocess.run([sys.executable, str(ROOT / "status.py")], capture_output=True,
                                 text=True, timeout=20,
                                 env=dict(os.environ, SUPERWHISPER_RUNTIME="/nonexistent")).stdout)
assert down["ok"] and down["running"] is False and down["error"], down
# Even with nothing running, the panel needs a unit to start and a wrapper to call.
assert down["cli"] and down["serviceUnit"], down

# A long transcript is a preview in the snapshot; copying it copies all of it,
# through stdin rather than one oversized argument.
import tempfile
assert s["last"]["truncated"] is False and dictation["truncated"] is False, (s["last"], dictation)
with tempfile.TemporaryDirectory() as scratch:
  scratch = Path(scratch)
  (scratch / "wl-copy").write_text("#!/bin/sh\ncat > \"$(dirname \"$0\")/copied\"\n")
  (scratch / "wl-copy").chmod(0o755)
  long_text = "word " * 40000
  (scratch / "meta.json").write_text(json.dumps({"result": long_text}))
  subprocess.run([sys.executable, str(ROOT / "status.py"), "--copy-entry", str(scratch)], check=True, timeout=20,
                 env=dict(os.environ, PATH=f"{scratch}:{os.environ['PATH']}"))
  assert (scratch / "copied").read_text() == long_text

# Search looks through all of history, not only the pages drawn, in the
# snapshot's own row shape; it counts every match and pages on through them.
found = snapshot("--older-dictations", "449", helper=("--history-search", "DICTATION 4"))
# "Older dictation 4", 40 to 49 and 400 to 448: the last are far past page one.
assert found["ok"] is True and found["matches"] == 60, found["matches"]
assert found["query"] == "DICTATION 4" and found["historyTotal"] == 450, found
assert len(found["history"]) == 60 and found["historyMore"] is False, len(found["history"])
assert found["history"][-1]["text"] == "Older dictation 448.", found["history"][-1]
assert set(found["history"][0]) == set(dictation), found["history"][0]
assert found["history"][0]["audio"] is False, found["history"][0]
rest = snapshot("--older-dictations", "449",
                helper=("--history-search", "dictation 4", "--history-before", str(found["history"][29]["timestamp"])))
# Older than the 30th match (418) is 419 on: a window pages on through matches.
assert [r["text"] for r in rest["history"]][:2] == ["Older dictation 419.", "Older dictation 420."], rest["history"][:2]
assert rest["matches"] == 30, rest["matches"]
none = snapshot(helper=("--history-search", "nothing like this"))
assert none["matches"] == 0 and none["history"] == [], none
# A search for text that looks like a flag is still a search, not a page.
flaglike = snapshot(helper=("--history-search", "--history-before"))
assert flaglike["query"] == "--history-before" and flaglike["matches"] == 0, flaglike
from status import arguments, first_match, preview
assert arguments(["status.py", "--history-search", "--history-before", "--history-before", "7"]) \
  == {"--history-search": "--history-before", "--history-before": "7"}
# A match past the preview is carried with the text around it, so it can be
# read and marked; one inside the preview leaves the preview as it was.
late = "word " * 2000 + "the needle here " + "tail " * 100
shown = preview(late, "NEEDLE")
assert shown.startswith("…") and "needle" in shown and len(shown) <= 4000, shown[:40]
assert preview(late, "word") == late[:4000] and preview(late) == late[:4000]
assert preview("short needle", "needle") == "short needle"
# Lowering "İ" makes two characters of one; the index is still into the text.
assert first_match("İx is", "I") == 0 and first_match("İx is", "s") == 4
assert first_match("Grüße aus München", "MÜNCHEN") == 10

# Usage stats for the Account tab: shaped for drawing, S1-Voice shown as S1,
# a year of weekly columns ending with this week, and hidden with no history.
stats = s["stats"]
assert [f["unit"] for f in stats["figures"]][:3] == ["words", "dictations", "spoken"], stats["figures"]
assert stats["figures"][0]["value"] == "12,035" and stats["figures"][2]["value"] == "1h 42m", stats["figures"]
assert {"value": "15", "unit": "day streak", "note": ""} in stats["figures"], stats["figures"]
assert len(stats["grid"]) == 52 * 7 and len(stats["months"]) == 52 and max(stats["grid"]) == 4, stats["grid"][-14:]
assert stats["figures"][-1]["unit"].startswith("Since ") and stats["saved"] == "3 hours" and stats["typing"] == "5h 0m" and stats["busiest"] in ("21:00", "9 PM"), stats
assert [m["name"] for m in stats["modes"]] == ["Cloud", "Offline", "Offline Lite"], stats["modes"]
assert stats["modeSummary"] == "", stats["modeSummary"]
from status import usage_stats
# With one mode there is nothing to compare, so the window says it instead.
alone = usage_stats({"enabled": True, "dictations": 3, "words": 30, "spokenMs": 9000, "today": "2026-10-12",
                     "days": [{"date": "2026-10-12", "words": 30}], "modes": [{"name": "Offline", "dictations": 3}]})
assert alone["modes"] == [] and alone["modeSummary"] == "All on Offline", alone
assert (alone["figures"][-1]["unit"], alone["saved"]) == ("Since Oct 12", "1 minute"), alone
# Hours as the clock reads them: the Omarchy bar's clock as set, else the locale.
from status import hour_label, twelve_hour_clock
import tempfile
assert (hour_label(21, True), hour_label(0, True), hour_label(12, True), hour_label(9, False)) == ("9 PM", "12 AM", "12 PM", "09:00")
assert usage_stats({"enabled": True, "dictations": 1, "words": 3, "today": "2026-10-12", "hours": [0] * 21 + [1, 0, 0]}, twelve=True)["busiest"] == "9 PM"
assert usage_stats({"enabled": True, "dictations": 1, "words": 3, "today": "2026-10-12"}, twelve=True)["hourLabels"] == ["12 AM", "6 AM", "12 PM", "6 PM"]
assert usage_stats({"enabled": True, "dictations": 1, "words": 3, "today": "2026-10-12"}, twelve=False)["hourLabels"] == ["00", "06", "12", "18"]
with tempfile.TemporaryDirectory() as config:
  previous = os.environ.get("XDG_CONFIG_HOME")
  os.environ["XDG_CONFIG_HOME"] = config
  os.makedirs(f"{config}/omarchy")
  for format, twelve in (("dddd h:mm AP", True), ("HH:mm", False), ("d MMMM 'W'ww yyyy", False), ("h:mm ap", True)):
    with open(f"{config}/omarchy/shell.json", "w") as f:
      json.dump({"bar": {"right": [{"id": "omarchy.clock", "format": format}]}}, f)
    assert twelve_hour_clock() is twelve, format
  if previous is None:
    del os.environ["XDG_CONFIG_HOME"]
  else:
    os.environ["XDG_CONFIG_HOME"] = previous
assert usage_stats({"enabled": False}) is None and usage_stats({"enabled": True, "dictations": 0}) is None
assert usage_stats({}) is None

# A row the desktop did not register gives the daemon's reason, not a bare "not registered".
from status import shortcut_display, with_double_tap
# Toggle can be a double tap of push to talk, named with its key, offered
# before Disabled; set, the row says so rather than the stored word.
row = with_double_tap({"value": "DoubleTap", "display": "Ctrl+Super+X · DoubleTap",
                       "options": [{"value": "DoubleTap", "label": "DoubleTap"}, {"value": "Alt+Space", "label": "Alt+Space"},
                                   {"value": "", "label": "Disabled"}, {"value": "__custom__", "label": "Record"}]},
                      {"hold": "RightAlt"})
assert [o["label"] for o in row["options"]] == ["Alt+Space", "Double-tap push to talk (RightAlt)", "Disabled", "Record"], row
assert row["display"] == "Double-tap push to talk (RightAlt)", row
assert "DoubleTap" not in [o["value"] for o in with_double_tap(dict(row, value="Alt+Space"), {"hold": ""})["options"]]
assert shortcut_display("Ctrl+Alt+H", {"toggle": "x"}, "hold", {"hold": "desktop_unavailable"}) == "Ctrl+Alt+H · desktop_unavailable"
assert shortcut_display("F9", {"toggle": "x"}, "cancel") == "F9 · not registered"

print(json.dumps({"contract": True, "no_application_imports": True, "runs_without_install": True}))
