#!/usr/bin/env python3
"""A stand-in for the Superwhisper daemon, so the panel can be worked on without it.

Serves the control-socket commands the panel reads, in the shape documented in
PROTOCOL.md, and remembers the changes the CLI sends, so the settings window can
be clicked through and show what it set. Nothing here is Superwhisper: it is a
fixture, and it exists so a contributor with no install (and no licence) can
still run and change the panel. It accepts what the real daemon would; it does
not validate the way the real daemon does.

    python3 tools/fake-daemon.py &                 # prints the runtime directory
    SUPERWHISPER_RUNTIME=<dir> python3 status.py   # one snapshot, as the panel reads it

Pass --phase recording, --idle, --no-last or --offline to pose a different state.

Vocabulary is the exception: the CLI edits the vocabulary file under
~/.config/superwhisper itself and only asks the daemon to reload, so a `vocab`
command run against this fixture still changes the real list.
"""
import argparse, json, os, socket, socketserver, sys, tempfile, threading, time
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--runtime", help="directory to hold control.sock (default: a temp dir)")
parser.add_argument("--phase", default="", help="idle, recording, transcribing, …")
parser.add_argument("--processing", default="offline", choices=["offline", "offline_lite", "cloud"])
parser.add_argument("--no-last", action="store_true", help="no previous dictation to show")
parser.add_argument("--not-ready", action="store_true", help="daemon up, models not loaded")
parser.add_argument("--models-missing", action="store_true",
                    help="the selected offline mode still needs its models")
parser.add_argument("--downloading", action="store_true",
                    help="the selected mode's missing model is a quarter downloaded")
parser.add_argument("--older-dictations", type=int, default=0, metavar="N",
                    help="N more dictations behind the last, past the 50 history_list returns")
parser.add_argument("--no-history-total", action="store_true",
                    help="answer history_list as a daemon released before it sent a total")
parser.add_argument("--no-history-paging", action="store_true",
                    help="answer history_list with the newest 50 whatever page is asked for, "
                         "as a daemon released before offset, limit and before")
parser.add_argument("--vocabulary-terms", type=int, default=0, metavar="N",
                    help="N more words in the vocabulary, for a long list")
parser.add_argument("--failed-dictation", action="store_true",
                    help="the newest dictation failed: no text, its error and its audio kept")
args = parser.parse_args()

LANGUAGES = {
  # The real cloud catalogue is 103 entries; this is long enough to exercise the
  # same branch, which is the one that gets a picker rather than stepping.
  "cloud": [("auto", "Automatic"), ("en", "English"), ("en-GB", "English (British)"),
            ("fr", "French"), ("de", "German"), ("el", "Greek"), ("ja", "Japanese"),
            ("es", "Spanish"), ("it", "Italian"), ("pt", "Portuguese"),
            ("nl", "Dutch"), ("pl", "Polish"), ("ru", "Russian"),
            ("zh", "Chinese"), ("ko", "Korean"), ("ar", "Arabic")],
  "offline": [("auto", "Automatic"), ("en", "English"), ("en-GB", "English (British)"),
              ("fr", "French"), ("de", "German"), ("el", "Greek")],
  # Offline Lite drops Greek, which is what makes the "mode cannot use it" path reachable.
  "offline_lite": [("auto", "Automatic"), ("en", "English"), ("en-GB", "English (British)"),
                   ("fr", "French"), ("de", "German")],
}
TONES = [("casual", "Casual"), ("semi-casual", "Semi-casual"), ("balanced", "Balanced"),
         ("semi-formal", "Semi-formal"), ("formal", "Formal")]
MODES = [("cloud", "Cloud"), ("offline", "Offline"), ("offline_lite", "Offline Lite")]


def rows(pairs):
  return [{"value": value, "label": label} for value, label in pairs]


def merge(into, change):
  """Fold a partial config into the stored one, as general_change does."""
  for key, value in change.items():
    if isinstance(value, dict) and isinstance(into.get(key), dict):
      merge(into[key], value)
    else:
      into[key] = value


LAST = None if args.no_last else {
  "text": "This is what the last dictation looked like.",
  "createdAt": time.time() - 90,
  "audio_seconds": 4.1,
  "release_to_text_ms": 396,
  "voiceModelID": "cohere-transcribe-q4",
  "languageModelID": "local",
  "language": "en",
  "delivery": "paste",
}

# Everything a change can touch. Each reply reads from here, so a change shows
# on the next poll the way it would against the real daemon.
lock = threading.Lock()
revision = 1
state = {
  "processing": args.processing,
  "general": {"language": "el" if args.processing != "cloud" else "en", "tone": "semi-formal",
              "launchAtLogin": True, "errorLoggingEnabled": True,
              "recordingPreservationPeriod": 1209600,
              "linux": {"historyEnabled": True, "saveRecordingAudio": False}},
  "audio": {"useDefaultInputDevice": False, "audioInputDeviceId": "alsa_input.usb-Fixture",
            "defaultPlaybackBehavior": "duck", "enableSoundEffects": True,
            "soundEffectVolume": 0.4, "showRecordingIndicator": True,
            "recordingIndicatorStyle": "edgeGlow", "enableSilenceRemoval": True,
            "favoriteDevices": [], "ignoredDevices": []},
  "gain": {},
  "shortcuts": {"hold": "RightAlt", "toggle": "Alt+Space", "cancel": "Escape"},
  "autoVocabulary": True,
  "vocabulary": {
    "terms": ["Omarchy", "Superwhisper"],
    "pronunciations": [{"word": "Omarchy", "sounds_like": "Oh Machi"},
                       {"word": "Omarchy", "sounds_like": "Omachi"}],
    "replacements": [{"original": "bobbers", "with": "Babur's"}],
  },
  "history": [] if args.no_last else [{
    "timestamp": int(time.time()) - 90,
    # Kept with its recording; the older fixture dictations were not.
    "audioPath": "/nonexistent/Output.ogg",
    "metadata": {
      "result": "This is what the last dictation looked like.",
      "duration": 4112, "modelName": "S1-Voice", "languageModelName": "S1 Mini",
      "recordingDevice": "alsa_input.usb-Fixture_Microphone.analog-stereo",
      "linux": {"createdAt": time.time() - 90, "delivery": "paste_sent"},
    },
  }],
  "license": {"state": "unlicensed", "linked": False, "lastError": None},
}
if args.failed_dictation:
  # As history.rs archives a failure: empty result (as the macOS app stores
  # one), the error in meta.linux, and the recording kept.
  state["history"].insert(0, {
    "timestamp": int(time.time()) - 30,
    "audioPath": "/tmp/superwhisper-fixture/Output.ogg",
    "metadata": {
      "result": "", "rawResult": "", "duration": 2700000, "modelName": "S1-Voice",
      "recordingDevice": "alsa_input.usb-Fixture_Microphone.analog-stereo",
      "linux": {"createdAt": time.time() - 30, "error": "Cloud transcription failed: HTTP 502"},
    },
  })
  # A dictation that heard nothing, as older archives may hold: not listed.
  state["history"].insert(1, {
    "timestamp": int(time.time()) - 60,
    "metadata": {"result": "", "duration": 900, "linux": {"createdAt": time.time() - 60}},
  })
# A fixed date, not the clock: each fixture daemon is a fresh process, and a
# pager that resumes "before" one daemon's oldest timestamp must find the same
# rows in the next one even when a second ticks over between them.
OLDER = 1_790_000_000
state["vocabulary"]["terms"] += [f"Term {n}" for n in range(args.vocabulary_terms)]
state["history"] += [{
  "timestamp": OLDER - n,
  "metadata": {"result": f"Older dictation {n}.", "duration": 1000,
               "linux": {"createdAt": OLDER - n}},
} for n in range(args.older_dictations)]


def language_label():
  code = state["general"].get("language")
  return dict(LANGUAGES["cloud"]).get(code, code)


def general_get(_):
  return {"revision": revision, "config": state["general"], "options": {
    "languages": rows(LANGUAGES[state["processing"]]),
    "tones": rows(TONES),
    "languageLabel": language_label(),
  }, "history": {"entries": len(state["history"])}}


def audio_get(_):
  devices = [
    {"name": "alsa_input.usb-Fixture", "description": "Fixture Microphone"},
    {"name": "alsa_input.pci-Builtin", "description": "Built-in Audio"},
    {"name": "alsa_input.gone", "description": "Unplugged", "availability": "disconnected"},
  ]
  for device in devices:
    if device["name"] in state["gain"]:
      device["volume"] = state["gain"][device["name"]]
  return {"revision": revision, "config": state["audio"], "devices": devices,
          "systemDefault": "alsa_input.pci-Builtin"}


def general_change(req):
  merge(state["general"], req.get("config") or {})
  return general_get(req)


def audio_change(req):
  audio = state["audio"]
  action, device = req.get("action"), req.get("device")
  if action == "select":
    audio["useDefaultInputDevice"] = device == ""
    audio["audioInputDeviceId"] = device
  elif action in ("favorite", "ignore"):
    key = "favoriteDevices" if action == "favorite" else "ignoredDevices"
    listed = audio[key]
    listed.remove(device) if device in listed else listed.append(device)
  elif action == "sounds":
    for key, value in req.items():
      if key not in ("version", "command", "action", "revision"):
        audio[key] = value
  return audio_get(req)


def audio_gain(req):
  state["gain"][req.get("device")] = req.get("volume")
  return {"ok": True}


def shortcuts_apply(req):
  merge(state["shortcuts"], req.get("shortcuts") or {})
  return {"shortcuts": state["shortcuts"]}


def models_select(req):
  state["processing"] = req.get("processing") or state["processing"]
  return REPLIES["models_get"](req)


def vocabulary_apply(req):
  state["vocabulary"] = req.get("config") or state["vocabulary"]
  return {"revision": revision, "config": state["vocabulary"]}


def history_delete(req):
  # The CLI sends the timestamp as it was typed, so compare spellings.
  state["history"] = [h for h in state["history"] if str(h["timestamp"]) != str(req.get("timestamp"))]
  return {"ok": True}


def history_list(req):
  """A page, as history.rs::list answers: newest first, `limit` of them (50
  unless asked, 1 to 500) from `offset` among those older than `before`."""
  if args.no_history_total:
    return {"items": state["history"][:50]}
  if args.no_history_paging:
    return {"items": state["history"][:50], "total": len(state["history"])}
  def number(value, default):
    try:
      return int(value)
    except (TypeError, ValueError):
      return default
  offset = max(0, number(req.get("offset"), 0))
  limit = min(500, max(1, number(req.get("limit"), 50)))
  before = number(req.get("before"), None)
  rows = sorted(state["history"], key=lambda h: -int(h["timestamp"]))
  if before is not None:
    rows = [h for h in rows if int(h["timestamp"]) < before]
  # A search pages through the dictations containing it, ignoring case.
  query = str(req.get("query") or "").strip()
  if query:
    rows = [h for h in rows if query.lower() in str(h["metadata"].get("result") or "").lower()]
  page = rows[offset:offset + limit]
  reply = {"items": page, "total": len(state["history"]), "offset": offset, "limit": limit,
           "more": offset + len(page) < len(rows)}
  if query:
    reply.update(query=query, matches=len(rows))
  return reply


def history_retry(req):
  """As main.rs answers: a failed dictation, transcribed again, saved in its place."""
  for entry in state["history"]:
    if str(entry["timestamp"]) == str(req.get("timestamp")):
      linux = entry["metadata"].get("linux") or {}
      if not linux.get("error") or entry["metadata"].get("result"):
        return {"error": "Only a failed dictation can be retried"}
      entry["metadata"] = dict(entry["metadata"], result="This is the retried dictation.",
                               rawResult="This is the retried dictation.",
                               linux=dict(linux, error=None))
      return {"ok": True, "session_id": 1}
  return {"error": "No such dictation in History"}


def history_clear(req):
  state["history"] = []
  return {"ok": True}


def license_activate(req):
  state["license"] = {"state": "pro", "linked": True, "lastError": None}
  return {"license": state["license"]}


def license_unlink(req):
  state["license"] = {"state": "unlicensed", "linked": False, "lastError": None}
  return {"license": state["license"]}


def auto_vocabulary_set(req):
  state["autoVocabulary"] = bool(req.get("enabled"))
  return {"enabled": state["autoVocabulary"]}


def acknowledged(_):
  # Downloads, model actions and the like: accepted, with nothing to show for it.
  return {"ok": True}


REPLIES = {
  "status": lambda _: {"ready": not args.not_ready, "phase": args.phase, "last": LAST},
  "models_get": lambda _: {
    "processing": state["processing"],
    "processingOptions": rows(MODES),
    # Every mode with what it still lacks: Offline Lite's model is never
    # downloaded here, so choosing it asks to download 680 MB first.
    "processingModes": [dict(row, missing=["parakeet-v3"] if row["value"] == "offline_lite" else [],
                             downloadBytes=680_000_000 if row["value"] == "offline_lite" else 0)
                        for row in rows(MODES)],
    # Cloud uses no local models; an offline mode names the ones it needs.
    "selectionModels": [] if state["processing"] == "cloud" else [
      {"id": "transcription", "ready": not args.models_missing},
      {"id": "vocabulary", "ready": True},
    ],
    "removingOffline": False,
    "active": "transcription" if args.downloading else None,
    "queued": [],
    "models": [{"id": "transcription", "sizeBytes": 2_000_000_000,
                "download": {"state": "downloading", "bytes": 500_000_000, "total": 2_000_000_000}
                if args.downloading else {"state": "missing" if args.models_missing else "installed"}},
               {"id": "vocabulary", "sizeBytes": 400_000_000, "download": {"state": "installed"}}],
  },
  "general_get": general_get,
  "history_list": history_list,
  "history_retry": history_retry,
  # Two weeks of dictation ending today, as history_stats reports it: from
  # recording_stat_lines, which History off stops adding to but keeps.
  "history_stats": lambda _: {
    "enabled": True, "dictations": 749, "words": 12035, "spokenMs": 6171000,
    "since": int(time.time()) - 14 * 86400, "today": time.strftime("%Y-%m-%d"),
    "days": [{"date": time.strftime("%Y-%m-%d", time.localtime(time.time() - n * 86400)),
              "words": w, "dictations": max(1, w // 16)}
             for n, w in enumerate([9, 27, 231, 1308, 3078, 836, 840, 265, 913, 1744, 999, 304, 21, 1299, 161])],
    "hours": [28, 31, 0, 0, 0, 0, 0, 2, 9, 69, 109, 14, 2, 5, 5, 2, 33, 54, 15, 7, 84, 143, 93, 44],
    "modes": [{"name": "Cloud", "dictations": 526}, {"name": "Offline", "dictations": 190},
              {"name": "Offline Lite", "dictations": 33}],
  },
  "vocabulary_get": lambda _: {"revision": revision, "config": state["vocabulary"]},
  "account_get": lambda _: {
    "usage": {"snapshot": {"usedWords": 66, "wordLimit": 10000,
                           "resetsAt": int(time.time()) + 86400},
              "stale": False, "lastError": None},
    "license": state["license"],
  },
  "shortcuts_get": lambda _: {"shortcuts": state["shortcuts"]},
  "auto_vocabulary_get": lambda _: {"enabled": state["autoVocabulary"], "capture": {}},
  "audio_get": audio_get,
  # Writes.
  "general_change": general_change,
  "audio_change": audio_change,
  "audio_gain": audio_gain,
  "shortcuts_apply": shortcuts_apply,
  "models_select": models_select,
  "vocabulary_apply": vocabulary_apply,
  "history_delete": history_delete,
  "history_clear": history_clear,
  "license_activate": license_activate,
  "license_unlink": license_unlink,
  "auto_vocabulary_set": auto_vocabulary_set,
  "models_action": acknowledged,
  "audio_preview": acknowledged,
  "general_reload": acknowledged,
  "audio_reload": acknowledged,
  "vocabulary_reload": acknowledged,
}
READS = {name for name in REPLIES if name.endswith("_get") or name in ("status", "history_list", "history_stats")}


class Handler(socketserver.StreamRequestHandler):
  def handle(self):
    global revision
    for line in self.rfile:
      try:
        req = json.loads(line)
      except ValueError:
        self.wfile.write(b'{"error":"bad request"}\n')
        continue
      command = req.get("command")
      reply = REPLIES.get(command)
      with lock:
        if reply and command not in READS:
          revision += 1
          print(f"{command} {json.dumps({k: v for k, v in req.items() if k not in ('version', 'command')})}",
                flush=True)
        body = reply(req) if reply else {"error": f"unknown command {command}"}
      self.wfile.write((json.dumps(body) + "\n").encode())
      self.wfile.flush()


class Server(socketserver.ThreadingUnixStreamServer):
  daemon_threads = True
  allow_reuse_address = True


runtime = Path(args.runtime) if args.runtime else Path(tempfile.mkdtemp(prefix="superwhisper-fake-"))
runtime.mkdir(parents=True, exist_ok=True)
path = runtime / "control.sock"
if path.exists():
  path.unlink()
server = Server(str(path), Handler)
print(f"SUPERWHISPER_RUNTIME={runtime}", flush=True)
try:
  server.serve_forever()
except KeyboardInterrupt:
  pass
finally:
  server.server_close()
  path.unlink(missing_ok=True)
