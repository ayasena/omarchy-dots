"""One status snapshot for the Omarchy panel, read from the daemon's control socket.

Self-contained on purpose: Omarchy loads this plugin on its own, so it holds no
copy of Superwhisper's language, tone or model lists and imports nothing from
the application tree. Every choice it offers is named by the daemon, in
`general_get.options` and `models_get.processingOptions`.
"""
import datetime
import json
import math
import os
import re
import shutil
import socket
import struct
import subprocess
import sys
from pathlib import Path


# A release install and a development one run different services, own different
# sockets and are driven by different wrappers. The panel has to act on the one it
# is actually reading, or its buttons reach a daemon that is not there: on a
# development machine that surfaces as a bare "No such file or directory
# (os error 2)" from a release binary that was never started.
INSTALLS = [
  ("superwhisper", "superwhisper", "superwhisper.service"),
  ("superwhisper-dev", "superwhisper-dev", "superwhisper-dev.service"),
]


def socket_paths():
  """Each candidate socket, with the wrapper and unit that belong to it."""
  base = Path(os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}")
  runtime = os.environ.get("SUPERWHISPER_RUNTIME")
  if runtime:
    # An explicit runtime still belongs to whichever install owns that directory.
    name = Path(runtime).name
    for directory, wrapper, unit in INSTALLS:
      if name == directory:
        return [(Path(runtime) / "control.sock", wrapper, unit)]
    return [(Path(runtime) / "control.sock", INSTALLS[0][1], INSTALLS[0][2])]
  # Release installs first, then a development service.
  return [(base / directory / "control.sock", wrapper, unit)
          for directory, wrapper, unit in INSTALLS]


def wrapper_path(wrapper):
  """The command that drives an install: the link its installer makes in
  ~/.local/bin, else the same name on PATH. Omarchy's package puts it in
  /usr/bin and makes the link only in its per-user setup, which fresh installs
  skipped (omacom/omarchy#15551), so every change failed with "No such file or
  directory (os error 2)"."""
  local = Path.home() / ".local/bin" / wrapper
  if not local.exists():
    found = shutil.which(wrapper)
    if found:
      return found
  return str(local)


def idle_install():
  """With nothing running, name the install that is actually present on disk."""
  for _, wrapper, unit in INSTALLS:
    if Path(wrapper_path(wrapper)).exists():
      return wrapper, unit
  return INSTALLS[0][1], INSTALLS[0][2]


def serving_install(path, wrapper, unit):
  """The install whose service is the process behind the socket. A socket's
  directory does not say which unit runs it: a wrapper pointed at another build
  serves that build's socket from its own unit, and stopping the unit the
  directory names then does nothing."""
  try:
    with socket.socket(socket.AF_UNIX) as s:
      s.settimeout(2)
      s.connect(str(path))
      pid = struct.unpack("3i", s.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))[0]
    cgroup = Path(f"/proc/{pid}/cgroup").read_text()
  except (OSError, struct.error):
    return wrapper, unit
  for _, installed_wrapper, installed_unit in INSTALLS:
    if f"/{installed_unit}" in cgroup:
      return installed_wrapper, installed_unit
  return wrapper, unit


def call(path, command, **params):
  with socket.socket(socket.AF_UNIX) as s:
    s.settimeout(2)
    s.connect(str(path))
    s.sendall((json.dumps({"version": 1, "command": command, **params}) + "\n").encode())
    reply = json.loads(s.makefile().readline())
  if isinstance(reply, dict) and reply.get("error"):
    raise RuntimeError(str(reply["error"]))
  return reply


# Chinese, Japanese and Korean are written without spaces, so splitting on
# whitespace counts a whole sentence as one word. Those characters each count
# as one; everything else still counts in words.
CJK_RANGES = (
  (0x3040, 0x30FF),  # hiragana and katakana
  (0x3400, 0x4DBF),  # CJK unified ideographs extension A
  (0x4E00, 0x9FFF),  # CJK unified ideographs
  (0xAC00, 0xD7AF),  # hangul syllables
  (0xF900, 0xFAFF),  # CJK compatibility ideographs
)


def counted_words(text):
  cjk, rest = 0, []
  for character in text:
    code = ord(character)
    if any(low <= code <= high for low, high in CJK_RANGES):
      cjk += 1
      rest.append(" ")
    else:
      rest.append(character)
  return cjk + len("".join(rest).split())


def last_dictation(last):
  if not isinstance(last, dict) or not last.get("text"):
    return None
  text = str(last["text"])
  return {
    "text": text[:2000],
    # The panel shows a preview; copying a longer one goes through --copy-last.
    "truncated": len(text) > 2000,
    "words": counted_words(text),
    "createdAt": last.get("createdAt"),
    "audioSeconds": last.get("audio_seconds"),
    "releaseToTextMs": last.get("release_to_text_ms"),
    "voiceModelID": last.get("voiceModelID"),
    "languageModelID": last.get("languageModelID"),
    "language": last.get("language"),
    "delivery": last.get("delivery"),
  }


def size_label(size):
  """Bytes as the download prompt states them: one decimal in GB, whole MB below."""
  try:
    size = int(size)
  except (TypeError, ValueError):
    return ""
  if size >= 1_000_000_000:
    return f"{size / 1_000_000_000:.1f} GB"
  return f"{max(1, round(size / 1_000_000))} MB"


def named(rows):
  """Keep only well-formed {value,label} rows, so one bad entry cannot empty a menu."""
  out = []
  for row in rows or []:
    if isinstance(row, dict) and row.get("label") and row.get("value") is not None:
      out.append({"value": str(row["value"]), "label": str(row["label"])})
  return out


def microphones(audio):
  config = audio.get("config") or {}
  rows = [{"value": "", "label": "System default"}]
  for row in audio.get("devices") or []:
    if row.get("ignored") or row.get("availability") in ("disconnected", "not available"):
      continue
    name = row.get("name")
    label = row.get("label") or row.get("description") or name
    if name and label:
      rows.append({"value": name, "label": label})
  # The default names the device it records from, as the row does once
  # chosen, so stepping onto it draws the final text at once instead of
  # widening when the next snapshot arrives. It falls back as audio.rs's
  # resolve does: the desktop's default when usable, otherwise the first.
  fallback = next((row for row in rows[1:] if row["value"] == audio.get("systemDefault")), rows[1] if len(rows) > 1 else None)
  if fallback:
    rows[0]["label"] = f'System default · {fallback["label"]}'
  selected = "" if config.get("useDefaultInputDevice", True) else config.get("audioInputDeviceId", "")
  # Unplugged, the chosen microphone is not shown: the one that records
  # meanwhile is.
  in_use = next((d.get("name") for d in audio.get("devices") or [] if d.get("selected")), None)
  if selected and in_use and not any(row["value"] == selected for row in rows):
    selected = in_use
  return rows, selected




# ---------------------------------------------------------------------------
# The configuration screen, in the order and grouping the terminal interface
# uses (settings_ui.rs ORDER). Each row carries what to show and what to run,
# so the window renders the screen without knowing any of these settings by
# name, and a row gains a choice here rather than in QML.
# ---------------------------------------------------------------------------

RETENTION = [0, 3600, 6 * 3600, 86400, 7 * 86400, 30 * 86400, 90 * 86400, 31536000]

# Rows that only mean something while another row holds a value say so, and the
# window hides them otherwise: with history off there are no recordings to keep
# and nothing to keep them for. `also` is the other side of the same rule — the
# rows a choice changes along with itself — so the window can draw both at once.
HISTORY_ON = {"key": "saveHistory", "value": "true"}
TONE_HELP = {
  "casual": "Lowercase with proper nouns and minimal punctuation.",
  "semi-casual": "Sentence starts and \"I\" capitalized, with reduced punctuation.",
  "balanced": "Your original casing, with lightly reduced punctuation.",
  "semi-formal": "Polished casing and punctuation.",
  "formal": "The most polished casing and punctuation.",
}
PLAYBACK = [("pause", "Pause"), ("keepPlaying", "Keep Playing"),
            ("duck", "Lower"), ("mute", "Mute"), ("muffle", "Muffle")]
INDICATOR = [("edgeGlow", "Edge glow"), ("pill", "Pill"), ("off", "Off")]


def retention_label(seconds):
  """The same ladder settings_ui.rs::retention_label prints."""
  if seconds == 0:
    return "Forever"
  if seconds == 3600:
    return "1 hour"
  if seconds < 86400 and seconds % 3600 == 0:
    return f"{seconds // 3600} hours"
  if seconds == 86400:
    return "1 day"
  if seconds == 31536000:
    return "1 year"
  # settings_ui.rs::retention_label prints "1 weeks" and "1 months" here; one of
  # anything reads as a count rather than a period, so this says "1 week".
  if seconds % (30 * 86400) == 0:
    return plural(seconds // (30 * 86400), "month")
  if seconds % (7 * 86400) == 0:
    return plural(seconds // (7 * 86400), "week")
  return plural(seconds // 86400, "day")


def plural(count, unit):
  return f"{count} {unit}" if count == 1 else f"{count} {unit}s"


# Which control a row is drawn with. The terminal interface draws tone as a
# ladder of dots and the short exclusive sets inline, so the window does too;
# a long catalogue gets a picker because stepping it is not a way to find
# anything. "cycle" is the plain ‹ value › the rest of the rows use.
# The common chords each shortcut offers before anyone has to record one, the
# same two lists settings_ui.rs::shortcut_presets hands the terminal screen.
SHORTCUT_PRESETS = {
  "hold": ["RightSuper", "RightControl", "RightAlt", "Ctrl+Space"],
  "toggle": ["Alt+Space", "Ctrl+Space", "RightSuper", "RightControl"],
  "cancel": ["Escape", "Alt+Space", "Ctrl+Space", "RightSuper"],
  # Its own slot, so push to talk keeps its key; only Hyprland binds a button.
  "mouse": ["Mouse4", "Mouse5"],
  # Live only while a dictation key is held, so a bare key is the point.
  "send": ["Space", "Return"],
}
# Outside Hyprland the GlobalShortcuts portal registers shortcuts: it has no
# syntax for a lone modifier, holds Escape only while recording, and Alt+Space
# is KRunner's on Plasma. settings_ui.rs::shortcut_presets keeps the same set.
DESKTOP_SHORTCUT_PRESETS = {
  "hold": ["F9", "Ctrl+Space", "Ctrl+Alt+Space"],
  "toggle": ["Ctrl+Space", "Ctrl+Alt+Space"],
  "cancel": ["Escape", "Shift+Escape"],
}


def in_hyprland():
  """The same test as platform.rs::in_hyprland."""
  return bool(os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")) or any(
    d.lower() == "hyprland" for d in os.environ.get("XDG_CURRENT_DESKTOP", "").split(":"))


def follows_focus():
  """The same test as platform.rs::follows_focus: the edge glow follows
  Hyprland's focused tile, or niri's focused output."""
  return in_hyprland() or bool(os.environ.get("NIRI_SOCKET")) or any(
    d.lower() == "niri" for d in os.environ.get("XDG_CURRENT_DESKTOP", "").split(":"))
# Chosen like any other option, but it records rather than applies.
CUSTOM = "__custom__"
# The toggle slot's "Double-tap push to talk": no key of its own
# (shortcuts.rs::DOUBLE_TAP).
DOUBLE_TAP = "DoubleTap"

SCALES = ("tone",)
SEGMENTED = ("processing", "indicator")
PICKER_ABOVE = 10


def control_for(key, options):
  if key in SCALES:
    return "scale"
  if key in SEGMENTED:
    return "segmented"
  return "picker" if len(options) > PICKER_ABOVE else "cycle"


def choice(key, label, value, options, commands, help_text):
  options = list(options)
  return {"key": key, "label": label, "kind": "choice", "action": None,
          "control": control_for(key, options),
          "value": str(value),
          "display": next((o["label"] for o in options if o["value"] == str(value)),
                          str(value)),
          "options": options, "set": commands, "help": help_text}


def switch(key, label, value, command, help_text):
  """A two-state row. The terminal interface draws these as On / Off."""
  value = bool(value)
  # Named as its own kind so the window can draw a switch rather than a choice
  # of two; the options stay, so a client without switches still works.
  return {"key": key, "label": label, "kind": "switch", "action": None,
          "control": "switch", "value": json.dumps(value),
          "display": "On" if value else "Off",
          "options": [{"value": "true", "label": "On"}, {"value": "false", "label": "Off"}],
          "set": command, "help": help_text}


def slider(key, label, percent, commands, help_text, available=True,
           unavailable="Unavailable"):
  """A level, as a percentage. `set` carries the same placeholders a choice does."""
  return {"key": key, "label": label, "kind": "slider", "action": None,
          "control": "slider" if available and commands else "text",
          "value": str(int(percent)), "display": f"{int(percent)}%" if available else unavailable,
          "options": [], "set": commands if available else [], "help": help_text}


def with_double_tap(row, keys):
  """Offer toggling by double-tapping push to talk, named with its key.

  Hyprland only: its key hook reports the taps (shortcuts.rs::DOUBLE_TAP).
  """
  hold = str(keys.get("hold") or "")
  options = [o for o in row["options"] if o["value"] != DOUBLE_TAP]
  label = f"Double-tap push to talk ({hold})"
  if hold:
    at = next(i for i, o in enumerate(options) if o["value"] in ("", CUSTOM))
    options.insert(at, {"value": DOUBLE_TAP, "label": label})
  row["options"] = options
  # Alone: after Omarchy's own toggle key it was cut off, and read as that key.
  if row["value"] == DOUBLE_TAP:
    row["display"] = label
  return row


def send_row(keys, taken, why):
  row = shortcut_row("send", "Send", keys,
                     "Finish a dictation and send it: the text goes in, then Return. "
                     "While holding push to talk, press this key; with toggle recording, "
                     "double-tap the toggle shortcut. It does nothing unless you are "
                     "dictating, so the key types normally the rest of the time.",
                     None, None, taken, why)
  # Shown on hovering the row's name: the window draws no help text.
  row["info"] = ("Finish and send in one go.\n\n"
                 "While holding push to talk, press this key. Superwhisper types "
                 "what you said, then presses Enter to send it.\n\n"
                 "Using toggle recording? Double-tap the toggle key instead.")
  return row


def readonly(key, label, display, help_text):
  return {"key": key, "label": label, "kind": "text", "action": None,
          "control": "text", "value": "", "display": display,
          "options": [], "set": [], "help": help_text}


def pairs(options):
  return [{"value": str(v), "label": l} for v, l in options]


def mic_percent(device):
  """The audio server reports a level like "40%"; a slider wants the number."""
  text = str((device or {}).get("volume") or "")
  digits = "".join(c for c in text if c.isdigit())
  return int(digits) if digits else 0


def same_keys(a, b):
  aliases = {"esc": "escape", "control": "ctrl", "super": "meta", "logo": "meta"}
  def keys(text):
    return sorted(aliases.get(p, p) for p in text.lower().replace(" ", "").split("+") if p)
  return bool(a) and bool(b) and keys(a) == keys(b)


def shortcut_display(chord, desktop, key, why=None):
  """What the row shows; the same rule as shortcuts.rs::display. Off Hyprland
  the desktop holds the real key (the user may have picked another one in its
  dialog), and a shortcut it never registered does nothing."""
  assigned = (desktop or {}).get(key) or ""
  if assigned:
    # The same keys in the desktop's spelling ("Shift+Esc") read as chosen.
    return chord if same_keys(assigned, chord) else assigned
  if not chord:
    return ""
  return f"{chord} · {(why or {}).get(key) or 'not registered'}" if desktop else chord


def shortcut_row(key, label, keys, help_text, desktop=None, system=None, taken=None, why=None):
  """The common chords, whatever is set now, Disabled, and recording a new one.

  Offering the usual answers first means nobody has to know the spelling the
  daemon accepts, and the row still steps with the arrow keys like its
  neighbours. "Record shortcut" is the one option that opens the recorder.

  Only choices the daemon would take are offered (shortcuts.rs::normalized): a
  chord another action already uses is left out, since one key cannot both
  record and cancel, and Disabled is left out where it would leave nothing to
  start a recording with. Stepping onto a choice that is then refused reads as a
  control that will not move.
  """
  chord = str(keys.get(key) or "")
  others = {str(keys.get(k) or "") for k in ("hold", "toggle", "cancel", "mouse", "send") if k != key} - {""}
  presets = SHORTCUT_PRESETS if in_hyprland() else DESKTOP_SHORTCUT_PRESETS
  # Nor one another binding holds (Omarchy's Ctrl+Space, say): saving refuses
  # it, so the row would snap straight back (shortcuts.rs::taken).
  held = list((taken or {}).keys())
  values = [v for v in presets.get(key, presets["toggle"])
            if v not in others and not any(same_keys(v, h) for h in held)]
  # Whatever is set now belongs in the list, so stepping away from it can step back.
  if chord and chord not in values:
    values.insert(0, chord)
  options = [{"value": v, "label": v} for v in values]
  other_recorder = any(keys.get(k) and keys.get(k) != DOUBLE_TAP
                       for k in ("hold", "toggle", "mouse") if k != key)
  if key in ("cancel", "send") or other_recorder:
    options.append({"value": "", "label": "Disabled"})
  options.append({"value": CUSTOM, "label": "Record shortcut (Enter)"})
  display = shortcut_display(chord, desktop, key, why) or "Disabled"
  # Omarchy's dictation keys reach Superwhisper too, so the row shows the
  # keys the system maps first, then any Superwhisper adds of its own.
  mapped = [str(k) for k in (system or {}).get(key) or [] if k]
  if mapped:
    extra = [chord] if chord and not any(same_keys(chord, k) for k in mapped) else []
    display = " · ".join(mapped + extra)
    help_text += ("\n\nOmarchy maps " + " and ".join(mapped) + " to this. A key chosen here "
                  "works as well; Omarchy's keep working.")
  if desktop is not None and key == "hold" and chord and chord == keys.get("toggle"):
    # One key for both: the toggle's binding taps and holds.
    display = f"{chord} · same as toggle"
  return {
    "key": key, "label": label, "kind": "choice", "action": None, "control": "cycle",
    "value": chord, "display": display, "options": options,
    "set": [["shortcuts", "set", key, "%chord"]],
    "help": help_text + "\n\nStep through the common chords, or choose Record shortcut to "
            "press the one you want.",
  }


def model_row(models):
  """Processing, plus the one action its models currently need.

  The daemon says which models this mode uses and whether each is present
  (`models_get.selectionModels`), so the panel offers Download or Delete without
  holding its own copy of which mode needs what.
  """
  # Every mode, where the daemon lists them all, each with what choosing it
  # would have to download first, so the window can ask before it does. An
  # older daemon lists only the modes ready to use.
  modes = models.get("processingModes")
  options = named(modes if modes else models.get("processingOptions"))
  by_value = {str(m.get("value")): m for m in modes or [] if isinstance(m, dict)}
  for option in options if modes else []:
    mode = by_value.get(option["value"]) or {}
    missing = [str(m) for m in mode.get("missing") or []]
    # One request that queues them all, sent after the mode is selected: a
    # download per model failed from the second on, since one runs at a time.
    option["download"] = [["models", "prepare"]] if missing else []
    option["downloadLabel"] = size_label(mode.get("downloadBytes")) if missing else ""
  row = choice("processing", "Processing", models.get("processing") or "",
               options, [["models", "select", "%s"]],
               "Where dictation is transcribed. Offline modes need their models "
               "downloaded before they can be selected.")
  # Cloud is the default; without an account it cannot transcribe, so the row
  # says what to do, as the terminal interface does beside it.
  if models.get("processing") == "cloud" and (models.get("credentials") or {}).get("available") is False:
    row["display"] = f'{row["display"]} · sign in under Account, or choose Offline'
    # Drawn beside the buttons by clients that show the choices themselves.
    row["note"] = "Sign in under Account, or choose Offline"
    row["help"] = ("Cloud needs a Superwhisper account. Sign in under Account, or choose "
                   "Offline to transcribe on this computer. " + row["help"])
  needed = models.get("selectionModels") or []
  missing = [m["id"] for m in needed if isinstance(m, dict) and not m.get("ready")]
  present = [m["id"] for m in needed if isinstance(m, dict) and m.get("ready")]
  # While the mode's models download, the row carries how far along they are,
  # across all of them, so the window draws one bar rather than one per file.
  queued = set(models.get("queued") or []) | ({models.get("active")} - {None})
  if missing and queued & set(missing):
    sizes = {m.get("id"): m for m in models.get("models") or [] if isinstance(m, dict)}
    # Every model the mode uses, each with its bytes so far: a model that has
    # finished counts as whole. The window measures against the models that
    # were missing when it first saw the download, since one that finishes
    # drops out of `missing` and a total over those alone would start again.
    per_model = []
    for entry in needed:
      if not isinstance(entry, dict):
        continue
      model = sizes.get(entry.get("id")) or {}
      download = model.get("download") or {}
      size = int(download.get("total") or model.get("sizeBytes") or 0)
      got = size if entry.get("ready") else min(size, int(download.get("bytes") or model.get("partialBytes") or 0))
      per_model.append({"id": str(entry.get("id")), "ready": bool(entry.get("ready")),
                        "done": got, "total": size})
    total = sum(m["total"] for m in per_model if not m["ready"])
    done = sum(m["done"] for m in per_model if not m["ready"])
    fraction = done / total if total else 0.0
    waiting = any(((sizes.get(m["id"]) or {}).get("download") or {}).get("state") == "waiting"
                  for m in per_model)
    row["progress"] = {"fraction": round(fraction, 4),
                       "label": "Waiting for connection" if waiting else f"Downloading {int(fraction * 100)}%",
                       "models": per_model}
  if models.get("removingOffline"):
    row["action"] = {"label": "Removing…", "key": "", "commands": [], "confirm": ""}
  elif "progress" in row:
    # The daemon refuses to delete mid-download, and Download is what is happening.
    row["action"] = None
  elif missing:
    row["action"] = {"label": "Download", "key": "D",
                     "commands": [["models", "prepare"]],
                     "confirm": ""}
  elif present:
    # Deleting a mode's models moves off it first: to the other offline mode
    # when that one is fully downloaded (its shared models are kept), to Cloud
    # otherwise. The delete is one request that unloads before it removes.
    current = str(models.get("processing") or "")
    names = {o["value"]: o["label"] for o in options}
    other = "offline_lite" if current == "offline" else "offline"
    other_ready = other in by_value and not (by_value[other].get("missing") or [])
    target = other if other_ready else "cloud"
    commands = [["models", "remove-offline", "--confirm"]]
    if current in ("offline", "offline_lite"):
      commands = [["models", "select", target],
                  ["models", "remove-offline", "--confirm", "--mode", current]]
    row["action"] = {"label": "Delete", "key": "X", "commands": commands,
                     "confirm": f"Unload and delete the {names.get(current, 'offline')} models? "
                                f"Superwhisper will switch to {names.get(target, 'Cloud')}."}
  return row


def configuration(general, models, audio, shortcuts, vocabulary):
  config = general.get("config") or {}
  linux = config.get("linux") or {}
  options = general.get("options") or {}
  sound = audio.get("config") or {}
  keys = shortcuts.get("shortcuts") or {}
  desktop_keys = shortcuts.get("desktop")
  system_keys = shortcuts.get("system")
  taken_keys = shortcuts.get("taken")
  why_keys = shortcuts.get("desktop_unavailable")
  devices = audio.get("devices") or []
  mics, microphone = microphones(audio)
  selected = next((d for d in devices if d.get("selected")), None)

  indicator = ("off" if sound.get("showRecordingIndicator") is False
               else "pill" if sound.get("recordingIndicatorStyle") == "pill" else "edgeGlow")
  effects = (0.0 if sound.get("enableSoundEffects") is False
             else float(sound.get("soundEffectVolume") or 1.0)) * 100

  return [
    {"group": "General", "rows": [
      choice("language", "Language", config.get("language") or "auto",
             named(options.get("languages")), [["general", "set", "language", "%j"]],
             "The spoken language. Automatic detects it on Cloud, and follows the desktop language offline."),
      dict(choice("tone", "Tone", config.get("tone") or "semi-formal",
                  named(options.get("tones")), [["general", "set", "tone", "%j"]],
                  "How firmly the cleanup model reshapes what you said."),
           # What each step does to a dictation, from the terminal interface's
           # help, for the note the window shows beside the scale.
           optionHelp=TONE_HELP),
      model_row(models),
      choice("indicator", "Visualization",
             indicator if follows_focus() or indicator != "edgeGlow" else "pill",
             pairs(INDICATOR if follows_focus() else INDICATOR[1:]),
             [["audio", "set", "showRecordingIndicator", "%notoff"],
              ["audio", "set", "recordingIndicatorStyle", "%stylejson"]],
             "How recording is shown on screen. Edge glow animates the active "
             "tile on Hyprland and the focused screen's edge on niri; elsewhere "
             "recording shows as the pill."),
    ]},
    {"group": "Vocabulary", "rows": [
      switch("autoVocabulary", "Auto-learn vocabulary", vocabulary.get("enabled"),
             [["vocab", "auto", "%onoff"]],
             "Learn English vocabulary from corrections you make after dictation, "
             "entirely offline."),
      # The window opens its own dialogs for this row (Settings::find_agent_words):
      # where it will look first, then the words found, to keep or skip.
      readonly("agentVocabulary", "Suggest words", "Search this computer…",
               "Find names and terms you use in your coding-agent prompts, notes, "
               "git commits and app names, to add to your vocabulary. It is a search "
               "of files on this computer: it asks first, and nothing is sent anywhere."),
    ]},
    {"group": "Sound", "rows": [
      dict(choice("microphone", "Microphone", microphone, mics, [["audio", "select", "%s"]],
                  "The input device to record from."),
           # "System default" alone does not say which device that is; the
           # terminal interface names it too.
           **({"display": f'System default · {selected.get("label") or selected.get("description")}'}
              if not microphone and selected and (selected.get("label") or selected.get("description"))
              else {})),
      # With no usable input there is no level to set, and a bare "Unavailable"
      # reads as a broken row next to a Microphone row still naming a device.
      # The daemon already says what is wrong and what to do about it, so the
      # explanation carries its sentence rather than a second guess at one.
      slider("micVolume", "Microphone volume", mic_percent(selected),
             [["audio", "gain", (selected or {}).get("name") or "", "%pct"]],
             "The recording level of the selected microphone." if selected is not None
             else (audio.get("deviceError")
                   or "No microphone is available to set a level for."),
             available=selected is not None,
             unavailable="No microphone"),
      slider("effectVolume", "Sound effect volume", effects,
             [["audio", "set", "soundEffectVolume", "%unit"],
              ["audio", "set", "enableSoundEffects", "%louder"]],
             "Volume of the start and stop sounds. Zero turns them off."),
      choice("playback", "Audio when dictating", sound.get("defaultPlaybackBehavior") or "pause",
             pairs(PLAYBACK), [["audio", "set", "defaultPlaybackBehavior", "%j"]],
             "What happens to other audio while you dictate."),
    ]},
    {"group": "Keyboard shortcuts", "rows": [
      shortcut_row("hold", "Push to talk", keys,
                   "Hold this key to record; release to finish.", desktop_keys, system_keys, taken_keys, why_keys),
      (with_double_tap if in_hyprland() else lambda row, _: row)(
        shortcut_row("toggle", "Toggle recording", keys,
                     "Press once to start recording, again to finish.", desktop_keys, system_keys, taken_keys, why_keys),
        keys),
      *([shortcut_row("mouse", "Mouse button", keys,
                      "Hold this side mouse button to record; release to finish. "
                      "It works alongside push to talk.", desktop_keys, None, taken_keys, why_keys)]
        if in_hyprland() else []),
      # Only Hyprland's key hook sees a key pressed during the hold.
      *([send_row(keys, taken_keys, why_keys)] if in_hyprland() else []),
      # Outside Hyprland cancel is Escape only while recording (Shift+Escape
      # until the desktop can do that), so it is shown and can be changed here.
      *([shortcut_row("cancel", "Cancel recording", keys,
                      "Press while recording to discard it.", desktop_keys, why=why_keys)]
        if not in_hyprland() else []),
      # No row for the cancel shortcut: push to talk ends by letting go, so only
      # toggle recording needs one, and Escape by default serves it. It stays
      # settable from the CLI, and the chords above still avoid it.
    ]},
    {"group": "Application", "rows": [
      switch("launchAtLogin", "Launch at login", config.get("launchAtLogin"),
             [["general", "set", "launchAtLogin", "%j"]],
             "Start Superwhisper with the desktop session."),
      switch("errorLogging", "Error logging", config.get("errorLoggingEnabled"),
             [["general", "set", "errorLoggingEnabled", "%j"]],
             "Send privacy-filtered crash reports. They exclude transcripts, "
             "recordings, clipboard content, licence data and identity."),
    ]},
    {"group": "History", "rows": [
      # The daemon refuses history off while recordings are kept ("Enable
      # history before saving recording audio"), so recordings go first, as the
      # terminal interface sends them. Turning history on writes recordings off,
      # which they already are: the daemon never holds one without the other.
      dict(switch("saveHistory", "Save history", linux.get("historyEnabled"),
                  [["general", "set", "linux.saveRecordingAudio", "false"],
                   ["general", "set", "linux.historyEnabled", "%j"]],
                  "Keep dictations in History, failed ones with their recording."),
           also={"false": {"saveRecordings": "false"}}),
      dict(switch("saveRecordings", "Save recording audio", linux.get("saveRecordingAudio"),
                  [["general", "set", "linux.saveRecordingAudio", "%j"]],
                  "Keep the original audio alongside each saved transcript. "
                  "A failed dictation keeps its audio either way."),
           requires=HISTORY_ON),
      dict(choice("retention", "Keep history",
             config.get("recordingPreservationPeriod") or 0,
             # A saved period that is not on the ladder is still a real setting,
             # so it joins the list in order rather than showing as a raw count.
             [{"value": str(v), "label": retention_label(v)}
              for v in sorted(set(RETENTION) | {int(config.get("recordingPreservationPeriod") or 0)})],
             [["general", "set", "recordingPreservationPeriod", "%n"]],
             "How long dictations are kept. Shortening this can delete existing history."),
           requires=HISTORY_ON),
    ]},
  ]



# ---------------------------------------------------------------------------
# The other three tabs. Each returns plain rows for the window to draw, in the
# order the terminal interface shows them.
# ---------------------------------------------------------------------------

# One page of the History tab: the first arrives with every snapshot, and the
# window asks for the next (`status.py --history-before TIMESTAMP`) as its list
# nears the end of what it holds.
HISTORY_LIMIT = 200
# The card profile a node name ends with, and the bus it starts with: wiring
# rather than identity. Only a device that has gone falls back to this; the
# terminal's history_details.rs keeps its own, shorter labels.
PROFILES = ("stereo", "mono", "surround", "fallback", "iec958", "hdmi")
BUSES = ("usb", "pci", "bluetooth", "platform", "firewire")


def short_device(name):
  """`alsa_input.usb-Vendor_Product.analog-stereo` reads as the device alone."""
  rest = None
  for prefix in ("alsa_input.", "alsa_output.", "alsa_card."):
    if name.startswith(prefix):
      rest = name[len(prefix):]
      break
  if rest is None:
    # A CoreAudio uid, or something else entirely; the last useful part will do.
    parts = [part for part in name.split(":") if part]
    return parts[2] if len(parts) > 2 else parts[1] if len(parts) > 1 else name
  head, dot, tail = rest.rpartition(".")
  if dot and head and any(key in tail for key in PROFILES):
    rest = head
  bus, dash, remainder = rest.partition("-")
  if dash and remainder and bus in BUSES:
    rest = remainder
  return rest.replace("_", " ").strip() or name


def grouped(number):
  """Counts group in thousands, the way the terminal interface prints them."""
  try:
    return f"{int(number):,}"
  except (TypeError, ValueError):
    return ""


def delivery_label(value):
  """`paste_sent` is a wire value, not something to show a person."""
  return {
    "paste": "Pasted",
    "paste_sent": "Pasted",
    "clipboard": "Copied to clipboard",
    "clipboard_only": "Copied to clipboard",
    "typed": "Typed",
    "none": "Not delivered",
  }.get(str(value), str(value).replace("_", " ").capitalize() if value else "")


def model_label(name):
  """History keeps the macOS app's model names; the app calls S1-Voice "S1"."""
  name = str(name or "")
  return {"S1-Voice": "S1"}.get(name, name)


def duration_label(milliseconds):
  """`duration` is milliseconds; settings_ui.rs prints the same ladder."""
  try:
    value = float(milliseconds)
  except (TypeError, ValueError):
    return ""
  if value <= 0:
    return ""
  if value < 1000:
    return f"{int(value)}ms"
  if value < 60000:
    return f"{value / 1000:.1f}s"
  seconds = int(value // 1000)
  return f"{seconds // 60}m {seconds % 60}s"


def history_total(history, general):
  """Every saved dictation, not just the newest 50 that history_list returns.

  A current daemon counts them all beside the list. One released before that
  sends no total there, but general_get has long carried the archive's count,
  kept current as dictations are saved, deleted and expire; the list's length is
  the last resort, and stops at 50.
  """
  for count in (history.get("total"), (general.get("history") or {}).get("entries")):
    if isinstance(count, int) and not isinstance(count, bool) and count >= 0:
      return count
  return len(history.get("items") or [])


def history_page(history):
  """Whether anything older than this page is left, and where it starts.

  `more` comes from a daemon that pages; one released before paging answered
  every request with its newest 50 and no `limit`, and asking it for another
  page would only bring the same 50 back, so nothing more is offered. The
  cursor is the page's oldest timestamp, a dictation without text included,
  so the next page starts after it whatever the window drew.
  """
  items = history.get("items") or []
  paged = "limit" in history and history.get("more") is True and bool(items)
  return {"historyMore": paged,
          "historyCursor": str(items[-1].get("timestamp") or "") if items else ""}


PREVIEW = 4000


def first_match(text, query):
  """Where `query` first appears in `text`, ignoring case, as an index into
  `text` itself: lowering can change a character's length ("İ"), so the
  lowered text is walked a character at a time."""
  needle = query.strip().lower()
  if not needle:
    return -1
  lowered, origin = "", []
  for at, char in enumerate(text):
    low = char.lower()
    lowered += low
    origin.extend([at] * len(low))
  found = lowered.find(needle)
  return origin[found] if found >= 0 else -1


def preview(text, query=None):
  """The part of a transcript a row carries. A search whose first match lies
  past the opening preview gets the text around the match instead, marked
  with a leading "…", so the match can be read and marked in the window."""
  if len(text) <= PREVIEW:
    return text
  at = first_match(text, query) if query else -1
  if at < 0 or at + len(query.strip()) <= PREVIEW:
    return text[:PREVIEW]
  start = at - 200
  space = text.rfind(" ", start - 40, start)
  start = space + 1 if space >= 0 else start
  return "…" + text[start:start + PREVIEW - 1]


def history_rows(items, devices=(), query=None):
  """Dictations, newest first, with the stats the details pane shows.

  A dictation names its microphone the way the audio server does; one still
  known reads by the description the Microphone row shows, so the two agree,
  and only a device that has gone falls back to a shortened system name.

  A failed dictation has no text, only `error` (Linux keeps it in
  meta.linux.error; the macOS app records none) and the audio it captured. It
  is listed with `failed` true, for the window to show as a failure. A row
  with neither text nor an error, which only an older archive holds, is left
  out as it always was.
  """
  described = {d.get("name"): d.get("label") or d.get("description")
               for d in devices if d.get("name") and (d.get("label") or d.get("description"))}
  rows = []
  for item in items[:HISTORY_LIMIT]:
    meta = item.get("metadata") or {}
    linux = meta.get("linux") or {}
    text = str(meta.get("result") or "")
    error = str(linux.get("error") or "")
    failed = bool(error) and not text
    if not text and not failed:
      continue
    rows.append({
      "text": preview(text, query),
      "failed": failed,
      "error": error if failed else "",
      "truncated": len(text) > PREVIEW,
      "words": counted_words(text),
      # `history delete` addresses a dictation by timestamp; the folder is what
      # "Show files" opens.
      "timestamp": item.get("timestamp"),
      "folder": str(Path(item.get("metaPath") or item.get("audioPath") or "").parent or ""),
      "createdAt": linux.get("createdAt") or item.get("timestamp"),
      "duration": duration_label(meta.get("duration")),
      # Playback: whether a recording was kept, and its length for the
      # progress bar, which counts from when the player started.
      "audio": bool(item.get("audioPath")),
      "durationMs": int(meta.get("duration") or 0),
      "model": model_label(meta.get("modelName")),
      "languageModel": str(meta.get("languageModelName") or ""),
      "delivery": delivery_label(linux.get("delivery")),
      "device": described.get(meta.get("recordingDevice"))
                or short_device(str(meta.get("recordingDevice") or "")),
    })
  return rows


def vocabulary_rows(vocabulary):
  """Words and replacements, each with its second value where it has one.

  A pronunciation belongs to its word rather than standing beside it, which is
  how vocabulary_ui.rs both lists and edits them: one row reading
  "Omarchy · sounds like Oh Machi", and one form whose second field is optional.
  """
  config = vocabulary.get("config") or {}
  pronunciations = {}
  for row in config.get("pronunciations") or []:
    word = str(row.get("word") or "")
    if word:
      sounds_like = str(row.get("sounds_like") or "")
      had = pronunciations.get(word.lower())
      pronunciations[word.lower()] = f"{had}, {sounds_like}" if had else sounds_like
  rows = []
  for term in config.get("terms") or []:
    term = str(term)
    if not term:
      continue
    rows.append({"kind": "Word", "primary": term,
                 "secondary": pronunciations.pop(term.lower(), "")})
  # A pronunciation whose word is no longer in the list still belongs to someone.
  for word, sounds_like in pronunciations.items():
    rows.append({"kind": "Word", "primary": word, "secondary": sounds_like})
  for row in config.get("replacements") or []:
    original = str(row.get("original") or "")
    if original:
      rows.append({"kind": "Replacement", "primary": original,
                   "secondary": str(row.get("with") or "")})
  return rows


def account_summary(account):
  """Allowance and plan. A stale snapshot is reported rather than shown as fact."""
  usage = account.get("usage") or {}
  snapshot = usage.get("snapshot") or {}
  licence = account.get("license") or {}
  used = snapshot.get("usedWords")
  limit = snapshot.get("wordLimit")
  state = str(licence.get("state") or "unlicensed")
  remaining = (limit - used) if isinstance(used, int) and isinstance(limit, int) else None
  # The daemon names an active licence "pro" (license.rs); "licensed" is not a
  # state it reports, so testing for it showed every Pro user as Free.
  pro = state == "pro"
  # The usage gauge, decided as account_ui.rs::usage_gauge decides it, so the
  # window fills a bar and prints a label without knowing the rules.
  if pro:
    disabled = licence.get("enableCloudModels") is False
    fraction, label, short = ((0.0, "Disabled by organization", "Disabled by organization") if disabled
                              else (1.0, "Unlimited cloud usage", "Unlimited cloud usage"))
  elif isinstance(used, int) and isinstance(limit, int) and limit > 0:
    count = f"{grouped(used)} / {grouped(limit)}"
    fraction = max(0.0, min(1.0, used / limit))
    label = f"{count} words · {grouped(max(0, limit - used))} remaining"
    short = f"{count} · {grouped(max(0, limit - used))} left"
  else:
    fraction = 0.0
    label = short = "Usage unavailable" if usage.get("lastError") else "—"
  return {
    "usageFraction": fraction,
    "usageLabel": label,
    # For a gauge too narrow for the whole sentence, as the terminal shortens it.
    "usageShortLabel": short,
    "usedWords": used,
    "wordLimit": limit,
    "remaining": remaining,
    # Grouped here so the window prints a number rather than building one.
    "usedLabel": grouped(used),
    "limitLabel": grouped(limit),
    "remainingLabel": grouped(remaining),
    "resetsAt": snapshot.get("resetsAt"),
    # The reset date as the person reads dates (their bar clock, or locale).
    "resetsLabel": date_label(snapshot.get("resetsAt")) if snapshot.get("resetsAt") else "",
    "stale": usage.get("stale") is True,
    "usageError": str(usage.get("lastError") or ""),
    "plan": "Superwhisper Pro" if pro else "Free",
    "licensed": pro,
    "licenseState": state,
    "licenseError": str(licence.get("lastError") or ""),
  }

# Usage stats for the Account tab, from the daemon's `history_stats`. Shaped
# here, as the gauge is, so the window draws them without doing sums. The
# figures follow the iOS Stats screen: typing is taken at 40 words a minute,
# the same constant (Stats.typingWordsPerMinute), so time saved agrees across
# platforms.
TYPING_WPM = 40
GRID_WEEKS = 52
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def spoken_label(ms):
  """iOS durationText: seconds under a minute, minutes under an hour, then both."""
  seconds = int(round(ms / 1000))
  if seconds < 60:
    return f"{seconds}s"
  if seconds < 3600:
    return f"{seconds // 60}m"
  return f"{seconds // 3600}h {seconds // 60 % 60}m"


def saved_label(ms):
  """iOS approximateSaved: one unit, written out."""
  minutes = int(round(ms / 60000))
  if minutes >= 60:
    return plural(int(round(minutes / 60)), "hour")
  return plural(max(minutes, 1), "minute")


def bar_clock_format():
  """The Omarchy bar clock's format, in Qt's notation, if there is one."""
  config = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
  try:
    shell = json.loads((config / "omarchy" / "shell.json").read_text())
  except (OSError, ValueError):
    shell = None
  found = []

  def walk(node):
    if isinstance(node, dict):
      if node.get("id") == "omarchy.clock" and isinstance(node.get("format"), str):
        found.append(node["format"])
      for value in node.values():
        walk(value)
    elif isinstance(node, list):
      for value in node:
        walk(value)

  walk(shell)
  return found[0] if found else None


def locale_format(item):
  """A format the locale writes, as nl_langinfo gives it."""
  import locale
  try:
    previous = locale.setlocale(locale.LC_TIME)
    locale.setlocale(locale.LC_TIME, "")
    try:
      return locale.nl_langinfo(item)
    finally:
      locale.setlocale(locale.LC_TIME, previous)
  except (locale.Error, AttributeError):
    return ""


def twelve_hour_clock():
  """Whether times read on a 12-hour clock: as the Omarchy bar's clock is set,
  which is the setting someone chose, or else as the locale writes them."""
  found = bar_clock_format()
  if found:
    # Qt's format: AP or ap (or A, a) is the AM/PM marker; quoted text is
    # literal.
    return "a" in re.sub(r"'[^']*'", "", found).lower()
  import locale
  try:
    previous = locale.setlocale(locale.LC_TIME)
    locale.setlocale(locale.LC_TIME, "")
    try:
      written = locale.nl_langinfo(locale.T_FMT)
    finally:
      locale.setlocale(locale.LC_TIME, previous)
  except (locale.Error, AttributeError):
    return False
  return any(code in written for code in ("%I", "%l", "%r", "%p"))


# Qt's date fields as strftime writes them; time fields are left out.
QT_DATE = {"dddd": "%A", "ddd": "%a", "dd": "%d", "d": "%-d", "MMMM": "%B", "MMM": "%b",
           "MM": "%m", "M": "%-m", "yyyy": "%Y", "yy": "%y"}
QT_FIELD = re.compile(r"'[^']*'|dddd|ddd|dd|d|MMMM|MMM|MM|M|yyyy|yy|hh|h|HH|H|mm|m|ss|s|zzz|z|AP|ap|A|a|t|ww|w")


def date_format():
  """How the person reads a date, as strftime writes it: the date part of the
  Omarchy bar's clock (ddd d MMM gives Sat 24 Oct), or else the locale's."""
  qt = bar_clock_format()
  if qt:
    out = []
    pos = 0
    for match in QT_FIELD.finditer(qt):
      out.append(qt[pos:match.start()].replace("%", "%%"))
      field = match.group()
      # A quoted literal, a time or a week number goes, with what joins it.
      out.append(QT_DATE.get(field, "\0"))
      pos = match.end()
    out.append(qt[pos:].replace("%", "%%"))
    written = "".join(out)
    # The separators a removed field leaves behind collapse, and none is left
    # at either end.
    written = re.sub(r"[\s:.,]*\x00[\s:.,]*", " ", written)
    written = re.sub(r"\s+", " ", written).strip(" :.,/-")
    if "%" in written:
      return written
  written = locale_format(__import__("locale").D_FMT)
  return written or "%Y-%m-%d"


def date_label(at):
  """A moment, given in seconds, as the person reads a date."""
  try:
    return datetime.datetime.fromtimestamp(int(at)).strftime(date_format())
  except (TypeError, ValueError, OverflowError, OSError):
    return ""


def hour_label(hour, twelve):
  """An hour of the day as the clock reads: 9 PM, or 21:00."""
  if twelve:
    return f"{hour % 12 or 12} {'AM' if hour < 12 else 'PM'}"
  return f"{hour:02d}:00"


def usage_stats(stats, twelve=None):
  """None with nothing counted yet, so the section stays hidden. An older
  daemon counted from History alone, and says `enabled` false with it off."""
  if not isinstance(stats, dict) or not stats.get("enabled") or not stats.get("dictations"):
    return None
  try:
    today = datetime.date.fromisoformat(str(stats.get("today")))
  except ValueError:
    return None
  words = int(stats.get("words") or 0)
  spoken = int(stats.get("spokenMs") or 0)
  by_day = {}
  for d in stats.get("days") or []:
    try:
      by_day[datetime.date.fromisoformat(str(d.get("date")))] = int(d.get("words") or 0)
    except ValueError:
      continue
  active = {day for day, count in by_day.items() if count > 0}

  def words_between(first, last):
    return sum(count for day, count in by_day.items() if first <= day <= last)

  this_week = words_between(today - datetime.timedelta(days=6), today)
  last_week = words_between(today - datetime.timedelta(days=13), today - datetime.timedelta(days=7))
  change = ""
  if last_week > 0:
    percent = round(abs(this_week - last_week) * 100 / last_week)
    change = f"{'↑' if this_week >= last_week else '↓'} {'999+' if percent > 999 else percent}% this week"
  # A streak still counts on a day not yet dictated in.
  day = today if today in active else today - datetime.timedelta(days=1)
  streak = 0
  while day in active:
    streak += 1
    day -= datetime.timedelta(days=1)

  if twelve is None:
    twelve = twelve_hour_clock()
  figures = [{"value": grouped(words), "unit": "word" if words == 1 else "words", "note": change},
             {"value": grouped(stats["dictations"]), "unit": "dictation" if stats["dictations"] == 1 else "dictations", "note": ""},
             {"value": spoken_label(spoken), "unit": "spoken", "note": ""}]
  if spoken >= 60000:
    figures.append({"value": str(round(words * 60000 / spoken)), "unit": "wpm", "note": ""})
  if streak >= 2:
    figures.append({"value": str(streak), "unit": "day streak", "note": ""})

  # The activity grid: a column a week, Monday at the top, this week last.
  # Levels 1-4 follow the square root of a day's words against the busiest
  # day's, so one huge day does not leave every other one blank; -1 is a day
  # still to come.
  start = today - datetime.timedelta(days=today.weekday() + 7 * (GRID_WEEKS - 1))
  busiest = max([by_day.get(start + datetime.timedelta(days=i), 0) for i in range(GRID_WEEKS * 7)] + [1])
  grid, months, shown = [], [], None
  for i in range(GRID_WEEKS * 7):
    day = start + datetime.timedelta(days=i)
    count = by_day.get(day, 0)
    grid.append(-1 if day > today else (math.ceil(math.sqrt(count / busiest) * 4) if count > 0 else 0))
    if i % 7 == 0:
      # A month is named over the first week that starts in it.
      months.append(MONTHS[day.month - 1] if shown is not None and day.month != shown else "")
      shown = day.month

  hours = [int(h or 0) for h in (stats.get("hours") or [])][:24]
  hours += [0] * (24 - len(hours))
  top = max(hours + [1])
  typing = words * 60000 / TYPING_WPM
  longest = max(typing, spoken, 1)
  modes = [m for m in stats.get("modes") or [] if m.get("name")][:3]
  most = max([int(m.get("dictations") or 0) for m in modes] + [1])
  since = stats.get("since")
  begun = datetime.date.fromtimestamp(since) if isinstance(since, (int, float)) else today
  begun = f"{MONTHS[begun.month - 1]} {begun.day}" + ("" if begun.year == today.year else f", {begun.year}")
  saved = saved_label(typing - spoken) if typing - spoken >= 30000 else ""
  # Where the figures began, last on their line, in a unit's place.
  figures.append({"value": "", "unit": f"Since {begun}", "note": ""})
  return {
    "saved": saved,
    "figures": figures,
    "grid": grid,
    "months": months,
    "typing": spoken_label(typing),
    # Shown on hover wherever typing time is used.
    "typingNote": f"Typing time assumes {TYPING_WPM} words per minute",
    "speaking": spoken_label(spoken),
    "typingFraction": typing / longest,
    "speakingFraction": spoken / longest,
    "hours": [h / top for h in hours],
    "busiest": hour_label(hours.index(max(hours)), twelve) if max(hours) > 0 else "",
    # Under the hours, every sixth.
    "hourLabels": [hour_label(h, twelve).replace(":00", "") for h in (0, 6, 12, 18)],
    # By processing mode, as the Processing setting names them. With one
    # mode a bar would compare it with nothing, so it is said instead.
    "modes": [{"name": str(m["name"]), "count": grouped(int(m.get("dictations") or 0)),
               "fraction": int(m.get("dictations") or 0) / most} for m in modes] if len(modes) > 1 else [],
    "modeSummary": f"All on {modes[0]['name']}" if len(modes) == 1 else "",
  }


def older_history(before=None, offset=None, query=None):
  """One page of older dictations, for a window that has drawn the ones before it.

  With a query, a page of the dictations containing it from all of history,
  not only the pages the window holds: the first page is the search, and
  `before` pages on through its matches as it does through the whole list.
  """
  params = {"limit": HISTORY_LIMIT}
  if before is not None:
    params["before"] = before
  if offset is not None:
    params["offset"] = offset
  if query:
    params["query"] = query
  error = "Superwhisper is not running"
  for path, _, _ in socket_paths():
    if not path.exists():
      continue
    try:
      history = call(path, "history_list", **params)
      try:
        devices = call(path, "audio_get").get("devices") or []
      except (OSError, ValueError, RuntimeError):
        devices = []
    except (OSError, ValueError, RuntimeError) as e:
      error = str(e) or error
      continue
    print(json.dumps({
      "ok": True,
      "history": history_rows(history.get("items") or [], devices, query),
      "historyTotal": history_total(history, {}),
      **history_page(history),
      # Every match, not only this page's. A daemon too old to search ignores
      # the query and sends its newest page with no count: none is reported,
      # so the window can say the search did not happen.
      **({"query": query, "matches": history.get("matches")} if query else {}),
    }))
    return
  print(json.dumps({"ok": False, "error": error}))


def copy(text):
  # Through stdin: a long transcript can exceed the limit on one argument.
  subprocess.run(["wl-copy"], input=text.encode(), timeout=10, check=False)


def copy_full(flag, value):
  """`--copy-last`, or `--copy-entry FOLDER`: copy the whole transcript the
  panel shows only a preview of."""
  if flag == "--copy-entry":
    folder = Path(value) if value else None
    if folder:
      try:
        meta = json.loads((folder / "meta.json").read_text())
      except (OSError, ValueError):
        meta = {}
      if meta.get("result"):
        copy(str(meta["result"]))
    return
  for path, _, _ in socket_paths():
    if not path.exists():
      continue
    try:
      last = call(path, "status").get("last") or {}
    except (OSError, ValueError, RuntimeError):
      continue
    if last.get("text"):
      copy(str(last["text"]))
    return


VALUED = ("--copy-entry", "--history-search", "--history-before", "--history-offset")


def arguments(argv):
  """The flags given, each with its value, read left to right: a value is
  never read as a flag, so searching for "--history-before" is a search."""
  found, at = {}, 1
  while at < len(argv):
    flag = argv[at]
    if flag in VALUED:
      found[flag] = argv[at + 1] if at + 1 < len(argv) else ""
      at += 2
    else:
      found[flag] = True
      at += 1
  return found


def serve():
  """`--serve`: one snapshot per request, without starting Python each time.

  Each line on stdin is a JSON list of the flags the command line takes ([]
  for the whole snapshot); each answer is one line of JSON. Starting the
  interpreter and importing this file cost three times the snapshot itself,
  every two seconds a settings window was open.
  """
  import contextlib, io
  for line in sys.stdin:
    try:
      flags = json.loads(line)
      if not isinstance(flags, list) or not all(isinstance(f, str) for f in flags):
        raise ValueError("a request is a list of flags")
      out = io.StringIO()
      with contextlib.redirect_stdout(out):
        run(["status.py", *flags])
      answer = out.getvalue().strip().replace("\n", " ") or json.dumps({"ok": False, "error": "no answer"})
    except Exception as e:  # one bad request must not end the helper
      answer = json.dumps({"ok": False, "error": str(e) or type(e).__name__})
    sys.stdout.write(answer + "\n")
    sys.stdout.flush()


def main():
  if sys.argv[1:] == ["--serve"]:
    serve()
    return
  run(sys.argv)


def run(argv):
  given = arguments(argv)
  for flag in ("--copy-last", "--copy-entry"):
    if flag in given:
      copy_full(flag, given[flag])
      return
  # `--history-before TIMESTAMP` (or `--history-offset N`): one older page of
  # the History tab rather than the whole snapshot.
  # `--history-search TEXT` searches all of history, and with either of those
  # pages on through the matches.
  query = given.get("--history-search")
  paging = {}
  for flag in ("--history-before", "--history-offset"):
    if flag in given:
      value = given[flag]
      paging[flag[10:]] = int(value) if value.isdigit() else 0
  if paging or query is not None:
    older_history(query=query, **paging)
    return
  error = "Superwhisper is not running"
  for path, wrapper, unit in socket_paths():
    if not path.exists():
      continue
    try:
      status = call(path, "status")
      models = call(path, "models_get")
      general = call(path, "general_get")
      audio = call(path, "audio_get")
      shortcuts = call(path, "shortcuts_get")
      vocabulary = call(path, "auto_vocabulary_get")
      # The remaining tabs. A daemon too old to answer one of these leaves that
      # tab empty rather than failing the whole snapshot.
      def optional(command, **params):
        try:
          return call(path, command, **params)
        except (OSError, ValueError, RuntimeError):
          return {}
      history = optional("history_list", limit=HISTORY_LIMIT)
      words = optional("vocabulary_get")
      account = optional("account_get")
      stats = optional("history_stats")
    except (OSError, ValueError, RuntimeError) as e:
      error = str(e) or error
      continue
    config = general.get("config") or {}
    options = general.get("options") or {}
    mics, microphone = microphones(audio)
    wrapper, unit = serving_install(path, wrapper, unit)
    print(json.dumps({
      "ok": True,
      "running": True,
      # The wrapper and unit belonging to the daemon that just answered, so an
      # action cannot be sent to the other install.
      "cli": wrapper_path(wrapper),
      "serviceUnit": unit,
      "ready": status.get("ready") is True,
      "phase": status.get("phase") or "",
      "processing": models.get("processing") or "",
      # Cloud plus each offline mode the daemon reports as ready to select.
      "processingOptions": named(models.get("processingOptions")),
      "language": config.get("language") or "auto",
      # Named even when this mode cannot use it, so the panel can say so.
      "languageLabel": options.get("languageLabel") or "Automatic",
      "languages": named(options.get("languages")),
      "tone": config.get("tone") or "semi-formal",
      "tones": named(options.get("tones")),
      "microphone": microphone,
      "microphones": mics,
      "last": last_dictation(status.get("last")),
      # The whole configuration screen, grouped and ordered as the terminal
      # interface draws it, so the window renders it without naming a setting.
      "configuration": configuration(general, models, audio, shortcuts, vocabulary),
      # Whether the desktop holds the recorder pause (outside Hyprland), so
      # the settings window can send it again after a service restart.
      "desktopPaused": shortcuts.get("desktop_paused"),
      "history": history_rows(history.get("items") or [], audio.get("devices") or []),
      "historyTotal": history_total(history, general),
      **history_page(history),
      "vocabulary": vocabulary_rows(words),
      "account": account_summary(account),
      "stats": usage_stats(stats),
    }))
    return
  wrapper, unit = idle_install()
  print(json.dumps({"ok": True, "running": False, "error": error,
                    "cli": wrapper_path(wrapper), "serviceUnit": unit}))


if __name__ == "__main__":
  main()
