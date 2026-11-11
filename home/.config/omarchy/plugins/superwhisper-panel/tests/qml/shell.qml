import Quickshell
import QtQuick
import qs.Commons as Commons

// Exercises the bar widget's own decision-making without a compositor or a
// daemon: its on/off switch, the rows it offers and the cursor that walks
// them. These are the parts that are wrong silently — a switch a stale
// snapshot throws back, a row the keyboard cannot reach — so none of them
// should rest on someone trying it.
ShellRoot {
  Item {
    id: harness

    property int failures: 0
    function check(name, got, want) {
      if (String(got) === String(want)) {
        console.log("  ok   " + name)
      } else {
        failures++
        console.log("  FAIL " + name + ": got " + JSON.stringify(got)
                    + ", wanted " + JSON.stringify(want))
      }
    }

    Component.onCompleted: {
      console.log("theme palette")
      // Qt 6.12's QtQuick has a type that shadows the palette's bare name from
      // qs.Commons; the widget must still be reading Omarchy's palette.
      var fg = Commons.Color.foreground
      check("text is the palette foreground",
            String(Qt.rgba(barPanel.foreground.r, barPanel.foreground.g, barPanel.foreground.b, 1)),
            String(Qt.rgba(fg.r, fg.g, fg.b, 1)))

      powerSwitchChecks()
    }

    // ---- The bar widget's on/off switch --------------------------------------
    // Driven against `true` in place of systemctl, so nothing here reaches a
    // real service; the snapshots the daemon would send are handed in directly.
    function snapshot(service, running) {
      service.applyStatus(JSON.stringify(running
        ? { ok: true, running: true, serviceUnit: "superwhisper.service" }
        : { ok: true, running: false, error: "Superwhisper is not running" }), ++service._snapshotSeq)
    }

    function powerSwitchChecks() {
      var service = barPanel.service
      service.serviceControl = "true"
      service.cli = "true"
      var fg = barPanel.barForeground
      var dimmed = Qt.darker(fg, 1.55)

      console.log("power switch: stopped")
      snapshot(service, false)
      check("the switch reads off", service.powerOn, false)
      check("no quit or start row is left", JSON.stringify(barPanel.rows), JSON.stringify(["power", "settings"]))
      check("the bar icon is dimmed", String(barPanel.barIconColor), String(dimmed))
      barPanel.cursorActive = true
      barPanel.rowIndex = 0
      check("the cursor starts on the switch", barPanel.currentRow, "power")
      barPanel.moveCursor(0, 1)
      check("down reaches Settings", barPanel.currentRow, "settings")
      barPanel.moveCursor(0, -1)
      check("up returns to the switch", barPanel.currentRow, "power")

      console.log("power switch: turning on by keyboard")
      barPanel.activateCursor()
      check("the knob moves at once", service.powerOn, true)
      check("and waits for the service", service.powerBusy, true)
      check("the bar icon follows the switch", String(barPanel.barIconColor), String(fg))
      snapshot(service, false)
      check("a snapshot from before the start leaves it on", service.powerOn, true)
      check("still waiting", service.powerBusy, true)
      snapshot(service, true)
      check("the service confirms it", service.powerBusy, false)
      check("nothing is flashed over the mode line", service.actionStatus, "")
      check("rows return with the service", barPanel.rows.indexOf("language") > 0, true)
      check("the switch is still the first stop", barPanel.rows[0], "power")
      check("no quit row while running", barPanel.rows.indexOf("quit"), -1)
      check("the bar icon is undimmed", String(barPanel.barIconColor), String(fg))

      console.log("choice pages: the cursor by click and by keyboard")
      barPanel.cursorActive = true
      barPanel.rowIndex = barPanel.rows.indexOf("language")
      barPanel.openPage("language", true)
      check("a click opens the page", barPanel.page, "language")
      check("a click leaves the cursor for the hover to place", barPanel.cursorActive, false)
      barPanel.leavePage(true)
      check("a click back leaves it off too", barPanel.cursorActive, false)
      barPanel.cursorActive = true
      barPanel.rowIndex = barPanel.rows.indexOf("language")
      barPanel.openPage("language")
      check("the keyboard keeps its cursor on the page", barPanel.cursorActive, true)
      barPanel.leavePage()
      check("and back on the setting's row", barPanel.currentRow, "language")
      // The start's own process has to finish before the switch takes another
      // press, as it would for someone clicking.
      powerOffTimer.start()
    }

    function powerOffChecks() {
      var service = barPanel.service
      var fg = barPanel.barForeground
      var dimmed = Qt.darker(fg, 1.55)
      console.log("power switch: turning off")
      check("ready for another press", service.powerBusy, false)
      barPanel.activate("power")
      check("the knob moves off at once", service.powerOn, false)
      check("the bar icon dims with it", String(barPanel.barIconColor), String(dimmed))
      snapshot(service, true)
      check("a stale running snapshot does not throw it back", service.powerOn, false)
      snapshot(service, false)
      check("the stop is confirmed", service.powerBusy, false)
      check("nor over OFF", service.actionStatus, "")

      console.log("power switch: started elsewhere")
      // A dictation key runs `superwhisper start`, which starts the service.
      snapshot(service, true)
      check("the switch follows an outside start", service.powerOn, true)
      check("without waiting on anything", service.powerBusy, false)
      check("the bar icon undims", String(barPanel.barIconColor), String(fg))
      snapshot(service, false)
      check("and an outside stop", service.powerOn, false)
      check("dimming the icon again", String(barPanel.barIconColor), String(dimmed))

      console.log("power switch: on while the models load")
      service.actionStatus = ""
      barPanel.activate("power")
      service.applyStatus(JSON.stringify({ ok: true, running: true, phase: "warming",
        serviceUnit: "superwhisper.service" }), ++service._snapshotSeq)
      check("the start is confirmed", service.powerBusy, false)
      check("loading is known before the status item shows it", service.warming, true)
      check("ON does not cover STARTING UP", service.actionStatus, "")
      service.applyStatus(JSON.stringify({ ok: true, running: true, phase: "idle",
        serviceUnit: "superwhisper.service" }), ++service._snapshotSeq)
      check("loaded", service.warming, false)

      console.log(failures === 0 ? "ALL OK" : failures + " FAILED")
      Qt.exit(failures === 0 ? 0 : 1)
    }

    property Timer powerOffTimer: Timer {
      interval: 500
      onTriggered: harness.powerOffChecks()
    }
  }

  BarPanel {
    id: barPanel
  }
}
