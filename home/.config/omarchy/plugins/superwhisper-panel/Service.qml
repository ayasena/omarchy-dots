import QtQuick
import Quickshell
import Quickshell.Io
import "Model.js" as Model

Item {
  id: root

  // Third-party plugins have no OMARCHY_PATH-style root; resolve our own directory.
  readonly property string pluginDir: decodeURIComponent(String(Qt.resolvedUrl(".")).replace(/^file:\/\//, "")).replace(/\/$/, "")
  property bool running: false
  property string phase: ""
  property string processing: ""
  property var processingOptions: []
  property string language: ""
  property string languageLabel: ""
  property var languages: []
  property string tone: ""
  property var tones: []
  property string microphone: ""
  property var microphones: []
  property var last: null
  property string actionStatus: ""
  // Shown inside the last-dictation card, so confirming a copy moves nothing.
  property bool copied: false
  property bool _refreshAgain: false
  // Set by a processing change; checked once the new mode's languages arrive.
  property var _languageBeforeSwitch: null

  readonly property string helperPath: pluginDir + "/status.py"
  // Which install to act on is the helper's answer, not a guess: a release and a
  // development service own different sockets, wrappers and units, and sending an
  // action to the wrong one fails with a bare "No such file or directory". These
  // hold the release install until the first snapshot names what is really there.
  property string cli: Quickshell.env("HOME") + "/.local/bin/superwhisper"
  property string serviceUnit: "superwhisper.service"

  function refresh() {
    if (pluginDir === "") return
    // A change can land while a snapshot is in flight; read again afterwards.
    if (statusProcess.running) { _refreshAgain = true; return }
    _inFlightSnapshot = ++_snapshotSeq
    statusProcess.running = true
  }

  // Snapshots are numbered as they start. One numbered at or below
  // _settledAfter began before the last write finished, so what it says about
  // anything editable is older than what the panel is already showing.
  property int _snapshotSeq: 0
  property int _inFlightSnapshot: 0
  property int _settledAfter: 0

  // Reassigning a list rebuilds every delegate drawn from it, so a snapshot
  // that says nothing new must leave it alone: the panel polls while open, and
  // rebuilding each time is a menu that never sits still.
  function _same(a, b) { return JSON.stringify(a) === JSON.stringify(b) }

  function applyStatus(raw, snapshot) {
    var parsed = Model.parseStatus(raw)
    if (!parsed.ok) return
    running = parsed.running === true
    if (parsed.cli) cli = String(parsed.cli)
    if (parsed.serviceUnit) serviceUnit = String(parsed.serviceUnit)
    phase = String(parsed.phase || "")
    if (!_same(last, parsed.last || null)) last = parsed.last || null
    _settlePower()

    // Every change is drawn the moment it is asked for. A snapshot taken while
    // one is still on its way would put the old value back for a poll, so the
    // editable state waits for a snapshot that started after the writes ended;
    // finishing them asks for exactly that one.
    if (writing || snapshot <= _settledAfter) return

    processing = String(parsed.processing || "")
    if (!_same(processingOptions, parsed.processingOptions || [])) processingOptions = parsed.processingOptions || []
    language = String(parsed.language || "")
    languageLabel = String(parsed.languageLabel || "")
    if (!_same(languages, parsed.languages || [])) languages = parsed.languages || []
    tone = String(parsed.tone || "")
    if (!_same(tones, parsed.tones || [])) tones = parsed.tones || []
    microphone = String(parsed.microphone || "")
    if (!_same(microphones, parsed.microphones || [])) microphones = parsed.microphones || []
    if (_languageBeforeSwitch && running && processing === _languageBeforeSwitch.mode) keepLanguageSupported()
  }

  // Each processing mode supports its own languages. When the saved one is not
  // among them, use Automatic (the desktop language) and say so, rather than
  // leaving a choice the model silently replaces with English.
  function keepLanguageSupported() {
    var before = _languageBeforeSwitch
    _languageBeforeSwitch = null
    if (Model.optionIndex(languages, language) >= 0) return
    setLanguage("auto")
    flash(before.modeLabel + " doesn't support " + before.label + ", so Language is now Automatic")
  }

  function setProcessing(value) {
    if (value === processing) return
    var mode = processingOptions[Model.optionIndex(processingOptions, value)]
    var index = Model.optionIndex(languages, language)
    _languageBeforeSwitch = {
      mode: value,
      modeLabel: mode ? String(mode.label) : "This mode",
      label: index >= 0 ? String(languages[index].label) : languageLabel
    }
    processing = value
    change(["models", "select", value], "processing")
  }

  // ---- Power ----------------------------------------------------------------
  // The panel's on/off switch starts and stops the service for this session,
  // as the tray's Quit did. It does not enable or disable the unit: Launch at
  // Login is a setting of its own, and the daemon puts the unit's enablement
  // back to match it each time it starts, so a `disable --now` here would not
  // even last until the next login. Nor does "off" stay off for long anyway:
  // Omarchy's dictation keys run `superwhisper start`, and the CLI starts the
  // service when it is not running, so the next key press turns it back on.
  //
  // What was asked for is held until a snapshot agrees (-1: follow the daemon),
  // as Omarchy's Tailscale service does, so the knob moves at once and stays
  // put while the service catches up, and a snapshot already on its way with
  // the old answer cannot throw it back.
  property int _desiredRunning: -1
  readonly property bool powerOn: _desiredRunning === -1 ? running : _desiredRunning === 1
  readonly property bool powerBusy: _desiredRunning !== -1
  // Replaced by the QML harness, so a test never reaches a real service.
  property string serviceControl: "systemctl"

  function setPower(on) {
    if (powerBusy || powerProcess.running) return
    _desiredRunning = on ? 1 : 0
    // systemd refuses a sixth start within ten seconds, a limit meant for a
    // crashing service, not someone flipping the switch; clear it first.
    powerProcess.command = on
      ? ["sh", "-c", '"$0" --user reset-failed "$1" 2>/dev/null; exec "$0" --user start "$1"',
         serviceControl, serviceUnit]
      : [serviceControl, "--user", "stop", serviceUnit]
    powerProcess.running = true
    powerDeadline.restart()
  }
  function togglePower() { setPower(!powerOn) }

  // A snapshot that shows the service where it was asked to be ends the wait.
  // Nothing is flashed: the mode line already says STARTING UP and then the
  // mode, or OFF, and a flash held over it would hide the next press.
  function _settlePower() {
    if (_desiredRunning === -1 || running !== (_desiredRunning === 1)) return
    _desiredRunning = -1
    powerDeadline.stop()
  }

  // Up, and loading its models into memory: from the daemon's first moment,
  // well before its status item shows the loading frame.
  readonly property bool warming: running && phase === "warming"

  // Same CLI commands as the tray menu; refresh afterwards so the panel shows
  // what the daemon accepted rather than what was asked for.
  //
  // Commands run one at a time, in the order they were asked for. A command
  // asked for while another runs waits its turn rather than being dropped — a
  // second click used to vanish, which read as a control that did not respond.
  // Each entry carries the setting it changes, so a newer value for that
  // setting replaces one still waiting: a held arrow sends where it ended
  // rather than every step on the way.
  property var _queue: []
  readonly property bool writing: changeProcess.running || _queue.length > 0

  function change(args, key) {
    _queue = _queue.filter(function (entry) { return entry.key !== key })
      .concat([{ argv: args.slice(), key: key }])
    _next()
  }
  function _next() {
    if (changeProcess.running || _queue.length === 0) return
    var entry = _queue[0]
    _queue = _queue.slice(1)
    changeProcess.command = [cli].concat(entry.argv)
    changeProcess.running = true
  }

  function setLanguage(value) {
    if (value === language) return
    language = value
    change(["general", "set", "language", JSON.stringify(value)], "language")
  }

  function setTone(value) {
    if (value === tone) return
    tone = value
    change(["general", "set", "tone", JSON.stringify(value)], "tone")
  }

  function setMicrophone(value) {
    if (value === microphone) return
    microphone = value
    change(["audio", "select", value], "microphone")
  }

  // The mode line is state only: an error is never shown over it. A refused
  // change is put right by the snapshot that follows, which shows the panel
  // what the daemon really holds.
  property bool actionIsError: false
  function flash(message, error) {
    actionStatus = message
    actionIsError = error === true
    actionStatusTimer.restart()
  }

  function copyLast() {
    if (!last || !last.text) return
    if (last.truncated)
      Quickshell.execDetached(["python3", helperPath, "--copy-last"])
    else
      Quickshell.execDetached(["wl-copy", "--", String(last.text)])
    copied = true
    copiedTimer.restart()
  }

  Timer {
    id: copiedTimer
    interval: 1500
    onTriggered: root.copied = false
  }

  Timer {
    id: actionStatusTimer
    interval: 4000
    onTriggered: root.actionStatus = ""
  }

  // Until a snapshot agrees with the switch, ask again every half second: a
  // started service takes a moment to open its socket. Likewise while it loads
  // its models, so STARTING UP goes the moment they are in memory.
  Timer {
    interval: 500
    repeat: true
    running: (root.powerBusy || root.warming) && !powerProcess.running
    onTriggered: root.refresh()
  }

  // A service that never gets there releases the switch, which then shows
  // where the service really is.
  Timer {
    id: powerDeadline
    interval: 15000
    onTriggered: {
      if (root._desiredRunning === -1) return
      root._desiredRunning = -1
      root.refresh()
    }
  }

  Process {
    id: powerProcess
    onExited: function (exitCode) {
      // A refusal releases the switch to where the service really is.
      if (exitCode !== 0 && root._desiredRunning !== -1) {
        root._desiredRunning = -1
        powerDeadline.stop()
      }
      root.refresh()
    }
  }

  Process {
    id: changeProcess
    stderr: StdioCollector {
      id: changeStderr
      waitForEnd: true
    }
    onExited: function(exitCode) {
      // Any snapshot already running began before this write landed.
      root._settledAfter = root._snapshotSeq
      if (exitCode !== 0) {
        root._languageBeforeSwitch = null
        var message = String(changeStderr.text || "").trim().split("\n").pop()
          .replace(/^Error: "?|"$/g, "")
        root.flash(message || "Could not change the setting", true)
      } else {
        // Saved, with something to know.
        var warning = String(changeStderr.text || "").split("\n")
          .filter(function (line) { return line.indexOf("Warning: ") === 0 }).pop()
        if (warning) root.flash(warning.slice(9))
      }
      // The snapshot after the last write is the one that confirms what was
      // drawn, or puts back whatever the daemon refused.
      if (root._queue.length > 0) root._next()
      else root.refresh()
    }
  }

  Process {
    id: statusProcess
    command: ["python3", root.helperPath]
    stdout: StdioCollector {
      id: statusStdout
      waitForEnd: true
    }
    onExited: function(exitCode) {
      if (exitCode === 0) root.applyStatus(statusStdout.text, root._inFlightSnapshot)
      if (root._refreshAgain) { root._refreshAgain = false; root.refresh() }
    }
  }
}
