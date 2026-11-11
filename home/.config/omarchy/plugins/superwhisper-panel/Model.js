function optionIndex(options, value) {
  for (var i = 0; i < (options || []).length; i++) {
    if (String(options[i].value) === String(value)) return i
  }
  return -1
}

function parseStatus(raw) {
  try {
    var parsed = JSON.parse(String(raw || "").trim())
    return parsed && typeof parsed === "object" ? parsed : { ok: false }
  } catch (e) {
    return { ok: false, lastError: "Could not read Superwhisper status" }
  }
}

// The hero's meta line: the processing mode. Modes are changed in Settings.
function processingLine(processing) {
  if (processing === "offline") return "Offline"
  if (processing === "offline_lite") return "Offline Lite"
  if (processing === "cloud") return "Cloud"
  return ""
}

// Tray frame names come from the status icon (IconRecording-recording-dark.svg).
function frameName(icon) {
  return String(icon || "").split("/").pop().split("-")[0]
}

// Loading has no label here: the panel's mode line says Starting up while the
// models load into memory. The icon still shows it.
function stateLabel(frame) {
  if (frame === "IconRecording") return "Recording"
  if (frame === "IconWorking") return "Processing"
  return ""
}


function seconds(value) {
  var n = Number(value)
  if (!isFinite(n) || n <= 0) return ""
  return n < 10 ? n.toFixed(1) + "s" : Math.round(n) + "s"
}

function ago(createdAt, nowSec) {
  var then = Number(createdAt)
  if (!isFinite(then) || then <= 0) return ""
  var delta = Math.max(0, Math.floor(nowSec - then))
  if (delta < 60) return "just now"
  if (delta < 3600) return Math.floor(delta / 60) + "m ago"
  if (delta < 86400) return Math.floor(delta / 3600) + "h ago"
  return Math.floor(delta / 86400) + "d ago"
}

// "17 words · 9.8s": what was said, not how it was processed.
function statsLine(last) {
  if (!last) return ""
  var parts = []
  var words = Number(last.words || 0)
  if (words > 0) parts.push(words + (words === 1 ? " word" : " words"))
  var audio = seconds(last.audioSeconds)
  if (audio) parts.push(audio)
  return parts.join(" · ")
}

if (typeof module !== "undefined") {
  module.exports = {
    optionIndex: optionIndex,
    parseStatus: parseStatus,
    processingLine: processingLine,
    frameName: frameName,
    stateLabel: stateLabel,
    ago: ago,
    statsLine: statsLine
  }
}
