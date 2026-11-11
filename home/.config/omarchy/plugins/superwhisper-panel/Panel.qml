import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import Quickshell.Services.SystemTray
import qs.Commons
import qs.Commons as Commons
import qs.Ui
import "Model.js" as Model
import "StatusGlyphs.js" as StatusGlyphs

Panel {
  id: root
  moduleName: "superwhisper"
  ipcTarget: "superwhisper"
  manageIpc: false

  // "" is the main page; a setting id drills the whole panel into its choices,
  // the way the tray menu opened submenus.
  property string page: ""
  property int rowIndex: 0
  property bool cursorActive: false
  property double nowSec: Date.now() / 1000

  readonly property color foreground: bar ? bar.foreground : Commons.Color.foreground
  readonly property color urgent: bar ? bar.urgent : Commons.Color.urgent
  readonly property color dim: Qt.darker(foreground, 1.55)
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family
  // Matches the size the Superwhisper tray item used (tray iconSizes 20).
  readonly property real iconSize: Math.max(8, Math.min(24, Number(setting("iconSize", 20))))
  // Omarchy that sets one icon size for the bar wants the resting mark that
  // size, as wide as Tailscale's; the setting then scales from it. The mark is
  // 613 of the em's 1000 units wide. Older Omarchy has no such size.
  readonly property real barGlyphSize: Style.bar.iconSize > 0
    ? Style.bar.iconSize * 1000 / 613 * iconSize / 20
    : Style.space(iconSize)

  // The daemon already animates its status item; follow its frames instead of
  // polling. The item reports Passive while this widget is in the bar.
  readonly property var trayItem: {
    var values = SystemTray.items.values
    for (var i = 0; i < values.length; i++) {
      if (String(values[i].id) === "superwhisper") return values[i]
    }
    return null
  }
  readonly property string frame: trayItem ? Model.frameName(trayItem.icon) : ""
  readonly property string liveState: Model.stateLabel(frame)

  // On is what the switch says while it waits for the service, and otherwise
  // the daemon answering — its snapshot, or its status item, which appears
  // the moment it starts (a dictation key starts it too) and goes when it stops.
  readonly property bool serviceOn: sw.powerBusy ? sw.powerOn : (sw.running || trayItem !== null)
  // Off reads at a glance in the bar the way Omarchy's Tailscale icon does:
  // the same glyph, in a dimmed foreground.
  readonly property color barIconColor: serviceOn ? barForeground : Qt.darker(barForeground, 1.55)
  readonly property string powerHint: sw.powerOn ? "Turn Superwhisper off" : "Turn Superwhisper on"

  // Processing only appears once an offline mode's models are downloaded.
  readonly property bool canChooseProcessing: sw.processingOptions.length > 1
  readonly property var settingRows: (canChooseProcessing ? [{ id: "processing", label: "Processing" }] : []).concat([
    { id: "language", label: "Language" },
    { id: "tone", label: "Tone" },
    { id: "microphone", label: "Microphone" }
  ])
  // The hero's on/off switch is the first cursor stop, as in Omarchy's own
  // Bluetooth and Tailscale panels; with the service off it and Settings are
  // all there is.
  readonly property var rows: ["power"].concat(sw.running
    ? settingRows.map(function(r) { return r.id }).concat(sw.last ? ["last", "history", "settings"] : ["history", "settings"])
    : ["settings"])
  readonly property var pageOptions: optionsFor(page)
  // On a choice page the cursor walks the back row (-1) and then the options.
  readonly property string currentRow: cursorActive && page === "" ? rows[Math.min(rowIndex, rows.length - 1)] : ""

  function optionsFor(id) {
    if (id === "processing") return canChooseProcessing ? sw.processingOptions : []
    if (id === "language") return sw.languages
    if (id === "tone") return sw.tones
    if (id === "microphone") return sw.microphones
    return []
  }

  function valueOf(id) {
    if (id === "processing") return sw.processing
    if (id === "language") return sw.language
    if (id === "tone") return sw.tone
    if (id === "microphone") return sw.microphone
    return ""
  }

  function titleOf(id) {
    for (var i = 0; i < settingRows.length; i++) if (settingRows[i].id === id) return settingRows[i].label
    return ""
  }

  function labelOf(id) {
    var options = optionsFor(id)
    var index = Model.optionIndex(options, valueOf(id))
    if (index >= 0) return String(options[index].label)
    return id === "language" && sw.languageLabel !== "" ? sw.languageLabel + ", unsupported" : ""
  }

  // The saved language is not one this processing mode can use.
  readonly property bool languageUnsupported: sw.running && sw.languages.length > 0
    && Model.optionIndex(sw.languages, sw.language) < 0

  // The keyboard cursor starts on the selected option, and goes back to the
  // setting's row on the way out. A click is different: the new page is laid
  // out under the pointer, whose hover then pulls the cursor to the row it is
  // over, so placing it first made the highlight jump to the selection and snap
  // back. A click leaves the cursor off and lets the hover place it.
  function openPage(id, byPointer) {
    page = id
    rowIndex = Math.max(0, Model.optionIndex(optionsFor(id), valueOf(id)))
    if (byPointer) cursorActive = false
    Qt.callLater(scrollCursorIntoView)
  }

  function leavePage(byPointer) {
    var from = page
    page = ""
    panelFlick.contentY = 0
    rowIndex = Math.max(0, rows.indexOf(from))
    if (byPointer) cursorActive = false
  }

  function choose(value, byPointer) {
    if (page === "processing") sw.setProcessing(value)
    else if (page === "language") sw.setLanguage(value)
    else if (page === "tone") sw.setTone(value)
    else if (page === "microphone") sw.setMicrophone(value)
    leavePage(byPointer)
  }

  function moveCursor(dx, dy) {
    cursorActive = true
    if (page !== "") {
      if (dx < 0) { leavePage(); return }
      if (dy === 0) return
      rowIndex = Math.max(-1, Math.min(pageOptions.length - 1, rowIndex + dy))
      scrollCursorIntoView()
      return
    }
    if (dx > 0 && optionsFor(currentRow).length > 0) { openPage(currentRow); return }
    if (dy === 0) return
    rowIndex = Math.max(0, Math.min(rows.length - 1, rowIndex + dy))
  }

  function setRowCursor(id) {
    cursorActive = true
    rowIndex = Math.max(0, rows.indexOf(id))
  }

  function activateCursor() {
    if (page !== "") {
      if (rowIndex < 0) leavePage()
      else if (rowIndex < pageOptions.length) choose(String(pageOptions[rowIndex].value))
      return
    }
    activate(currentRow)
  }

  // Settings is the GPUI window, opened through the CLI as the tray and the
  // launcher entry open it: one instance, raised on the tab asked for. Where
  // no window can open, the CLI falls back to the terminal interface itself,
  // so the click never does nothing.
  function openSettings(tab) {
    Quickshell.execDetached([sw.cli, "settings"].concat(tab ? [tab] : []))
  }

  function activate(id) {
    if (optionsFor(id).length > 0) openPage(id)
    else if (id === "last") sw.copyLast()
    else if (id === "history") { root.openSettings("history"); root.close() }
    else if (id === "settings") { root.openSettings(""); root.close() }
    else if (id === "power") sw.togglePower()
  }

  function scrollCursorIntoView() {
    if (page === "" || rowIndex < 0 || rowIndex >= optionColumn.children.length) return
    var item = optionColumn.children[rowIndex]
    Qt.callLater(function() {
      if (!item) return
      var margin = Style.space(6)
      var top = item.mapToItem(panelFlick.contentItem, 0, 0).y
      var bottom = top + item.height
      var maxY = Math.max(0, panelFlick.contentHeight - panelFlick.height)
      if (top < panelFlick.contentY + margin) panelFlick.contentY = Math.max(0, top - margin)
      else if (bottom > panelFlick.contentY + panelFlick.height - margin) panelFlick.contentY = Math.min(maxY, bottom + margin - panelFlick.height)
    })
  }

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  // In the middle of the bar, beside the clock, the panel opens centred under
  // the bar and holds the centre still while open, as Omarchy's weather and
  // calendar panels do. Worked out on each open, since the widget can be moved.
  property bool centredOnBar: false

  function inMiddleOfBar() {
    var window = root.QsWindow.window
    if (!window) return false
    var vertical = root.bar && root.bar.vertical
    var at = root.mapToItem(null, root.width / 2, root.height / 2)
    var span = vertical ? window.height : window.width
    var middle = vertical ? at.y : at.x
    return span > 0 && middle > span / 3 && middle < span * 2 / 3
  }

  function openPanel() {
    root.centredOnBar = root.inMiddleOfBar()
    root.open()
    // After showing: showing hands the popout over, and the panel it closes
    // clears the shared flag on its way out.
    if (root.centredOnBar) Qt.callLater(function() {
      if (root.opened && root.bar) root.bar.setCenterHoverRevealSuppressed(true)
    })
  }

  function togglePanel() {
    if (root.opened) root.close()
    else root.openPanel()
  }

  onOpenedChanged: if (!opened && centredOnBar && bar) {
    bar.setCenterHoverRevealSuppressed(false)
  } else if (opened) {
    page = ""
    cursorActive = false
    rowIndex = 0
    nowSec = Date.now() / 1000
    panelFlick.contentY = 0
    sw.refresh()
    Qt.callLater(function() { keyCatcher.forceActiveFocus() })
  }
  // A finished dictation lands on the complete frame; pick up its text and stats.
  onFrameChanged: if (frame === "IconComplete" || frame === "IconReady") sw.refresh()
  // The daemon's status item comes and goes with the service, whoever started
  // or stopped it: read the new state rather than waiting for the next open.
  onTrayItemChanged: sw.refresh()

  Service {
    id: sw
  }
  // For the QML harness, which drives the switch against a stand-in systemctl.
  property alias service: sw

  // omarchy-shell superwhisper page language — also handy for keybindings.
  IpcHandler {
    target: root.ipcTarget
    function open(): void { root.openPanel() }
    function close(): void { root.close() }
    function show(): void { root.openPanel() }
    function hide(): void { root.close() }
    function toggle(): void { root.togglePanel() }
    function refresh(): string { sw.refresh(); return "ok" }
    function page(name: string): string {
      if (root.optionsFor(name).length === 0) return "unknown page: " + name
      root.openPanel()
      Qt.callLater(function() { root.openPage(name) })
      return "ok"
    }
  }

  Component.onCompleted: sw.refresh()

  FontLoader { id: statusFont; source: "SuperwhisperStatus.ttf" }

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    // Drawn below rather than handed to the button: Omarchy fits an icon by
    // its measured ink, and Qt measures a glyph's ink down to the baseline, so
    // the mark, which floats above it, came out shrunk and set high. Fitting
    // the ink would also shrink the mark whenever a frame adds the status dot.
    iconComponent: Component { Item {} }

    StatusGlyph {
      // Exact, not anchored: centerIn snaps to a whole pixel, off the
      // underline the open panel draws.
      x: (button.width - width) / 2
      y: (button.height - height) / 2
      centred: true
      size: root.barGlyphSize
      frameName: root.frame !== "" ? root.frame : "IconReady"
      color: root.barIconColor
    }

    onPressed: function(buttonCode) {
      if (buttonCode === Qt.RightButton) root.openSettings("")
      else root.togglePanel()
    }
  }

  KeyboardPanel {
    id: panel
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.opened
    centerOnBar: root.centredOnBar
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(360))
    contentHeight: panel.fittedContentHeight(column.implicitHeight, Style.space(560))

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      onMoveRequested: function(dx, dy) {
        if (!root.cursorActive) { root.cursorActive = true; return }
        root.moveCursor(dx, dy)
      }
      onActivateRequested: if (root.cursorActive) root.activateCursor()
      onCloseRequested: root.close()
      onTabRequested: function(direction) { root.switchPanel(direction) }
      onTextKey: function(t) {
        var key = t.toLowerCase()
        if (key === "c") sw.copyLast()
        else if (key === "r") sw.refresh()
      }

      Flickable {
        id: panelFlick
        anchors.fill: parent
        contentWidth: width
        contentHeight: column.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        flickableDirection: Flickable.VerticalFlick
        interactive: contentHeight > height
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

        // Inset from the scroll area's clipped edges, so a row's border and
        // the logo are never shaved at a fractional scale.
        Column {
          id: column
          x: Style.space(2)
          width: panelFlick.width - Style.space(4)
          spacing: Style.space(12)

          Hero { width: parent.width }

          PanelSeparator { foreground: root.foreground }

          // ---- Main page ----------------------------------------------------

          Column {
            visible: root.page === "" && sw.running
            width: parent.width
            spacing: Style.space(6)

            Repeater {
              model: root.settingRows
              SettingRow {
                required property var modelData
                rowId: modelData.id
                label: modelData.label
                value: root.labelOf(modelData.id)
                warning: modelData.id === "language" && root.languageUnsupported
              }
            }
          }

          PanelSeparator {
            visible: root.page === "" && sw.running
            foreground: root.foreground
          }

          // The latest dictation and the way into the rest of history, as one section.
          Column {
            visible: root.page === "" && sw.running
            width: parent.width
            spacing: Style.space(6)

            LastDictation {
              visible: sw.last !== null
              width: parent.width
            }

            ActionRow {
              rowId: "history"
              glyph: "󰋚"
              label: "View history"
              chevron: true
            }
          }

          PanelSeparator {
            visible: root.page === "" && sw.running
            foreground: root.foreground
          }

          Column {
            visible: root.page === ""
            width: parent.width
            spacing: Style.space(6)

            ActionRow {
              rowId: "settings"
              glyph: "󰒓"
              label: "Settings"
            }
          }

          // ---- Choice page --------------------------------------------------

          Column {
            visible: root.page !== ""
            width: parent.width
            spacing: Style.space(6)

            BackRow { width: parent.width }

            Column {
              id: optionColumn
              width: parent.width
              spacing: Style.space(2)

              Repeater {
                model: root.pageOptions
                OptionRow {
                  required property var modelData
                  required property int index
                  width: optionColumn.width
                  option: modelData
                  optionIndex: index
                }
              }
            }
          }
        }
      }
    }
  }

  // Keeps "2m ago" honest while the panel stays open.
  Timer {
    interval: 30000
    repeat: true
    running: root.opened
    onTriggered: root.nowSec = Date.now() / 1000
  }

  // While open, the switch follows a service started or stopped elsewhere — a
  // dictation key, the terminal — within a few seconds even where no status
  // item announces it.
  Timer {
    interval: 3000
    repeat: true
    running: root.opened && !sw.powerBusy
    onTriggered: sw.refresh()
  }

  component StatusGlyph: Item {
    id: glyphRoot
    property real size: Style.font.icon
    property string frameName: "IconReady"
    property color color: root.foreground
    readonly property var marker: StatusGlyphs.markers[frameName]
    // The font keeps each frame where the macOS template put it, off centre
    // to leave room for the status dot. Shifting by the ink's distance from
    // the em's middle centres what is drawn, so the bar's underline sits
    // under the mark rather than beside it.
    // Only where the glyph is centred (the bar icon): a glyph set against an
    // edge, as the panel's own logo is, would be pushed past that edge.
    property bool centred: false
    readonly property real inkShift: !centred ? 0
      : (500 - (StatusGlyphs.inkCenters[frameName] || StatusGlyphs.inkCenters.IconReady)) / 1000 * Math.round(size)

    implicitWidth: size
    implicitHeight: size
    width: size
    height: size

    Text {
      x: glyphRoot.inkShift
      width: parent.width
      height: parent.height
      visible: statusFont.status === FontLoader.Ready
      text: StatusGlyphs.frames[glyphRoot.frameName] || StatusGlyphs.frames.IconReady
      color: glyphRoot.color
      font.family: statusFont.name
      font.pixelSize: Math.round(glyphRoot.size)
      horizontalAlignment: Text.AlignHCenter
      verticalAlignment: Text.AlignVCenter
    }

    // Recording, working and loading carry the macOS status colors.
    Text {
      x: glyphRoot.inkShift
      width: parent.width
      height: parent.height
      visible: statusFont.status === FontLoader.Ready && glyphRoot.marker !== undefined
      text: glyphRoot.marker ? glyphRoot.marker.glyph : ""
      opacity: glyphRoot.marker ? glyphRoot.marker.opacity : 0
      color: glyphRoot.marker && glyphRoot.marker.color ? glyphRoot.marker.color : glyphRoot.color
      font.family: statusFont.name
      font.pixelSize: Math.round(glyphRoot.size)
      horizontalAlignment: Text.AlignHCenter
      verticalAlignment: Text.AlignVCenter
    }
  }

  // PanelHero's layout; the meta line says how dictation is processed.
  component Hero: Item {
    id: heroRoot
    readonly property color heroDim: Qt.darker(root.foreground, 1.4)
    implicitHeight: Math.max(heroIcon.implicitHeight, heroLabels.implicitHeight, powerSwitch.implicitHeight)

    // Status only — the switch owns turning it on and off.
    StatusGlyph {
      id: heroIcon
      anchors.left: parent.left
      anchors.verticalCenter: parent.verticalCenter
      size: Style.font.display
      frameName: "IconReady"
      color: root.foreground
      opacity: sw.running ? 1.0 : 0.5
    }

    // Compact on/off switch on the trailing edge of the hero, and the header's
    // only cursor target, as in Omarchy's Bluetooth and Tailscale panels. It
    // starts and stops the service; see Service.qml's setPower for why it
    // leaves Launch at Login alone, and why a dictation key turns it back on.
    ToggleSwitch {
      id: powerSwitch
      objectName: "powerSwitch"
      checked: sw.powerOn
      busy: sw.powerBusy
      hasCursor: root.currentRow === "power"
      foreground: root.foreground
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      onHovered: function(on) { if (on) root.setRowCursor("power") }
      onToggled: sw.togglePower()

      PanelToolTip {
        visible: powerSwitch.containsMouse
        text: root.powerHint
        fontFamily: root.fontFamily
      }
    }

    Column {
      id: heroLabels
      anchors.left: heroIcon.right
      anchors.leftMargin: Style.space(14)
      anchors.right: parent.right
      anchors.rightMargin: powerSwitch.width + Style.space(12)
      anchors.verticalCenter: parent.verticalCenter
      spacing: Style.space(2)

      Row {
        width: parent.width
        spacing: Style.space(8)

        Text {
          id: heroTitle
          textFormat: Text.PlainText
          text: "superwhisper"
          color: root.foreground
          font.family: root.fontFamily
          font.pixelSize: Style.font.subtitle
          font.bold: true
        }
      }

      Text {
        textFormat: Text.PlainText
        width: parent.width
        // A passing status takes the mode line's place for a moment instead
        // of a line of its own, which pushed the panel down. Never an error:
        // those belong to the Settings window.
        readonly property string message: sw.actionIsError ? "" : sw.actionStatus
        text: message !== "" ? message
            // Starting up from the moment the switch goes on until the models
            // are in memory; off the moment it goes off, as stopping is quick.
            : (((sw.powerBusy && sw.powerOn) || sw.warming || root.frame === "IconLoading") ? "Starting up"
              : sw.powerOn ? Model.processingLine(sw.processing) : "Off").toUpperCase()
        color: heroRoot.heroDim
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        font.bold: true
        font.letterSpacing: 1.2
        elide: Text.ElideRight
      }
    }

    // Live state while recording or processing, pinned beside the switch and
    // kept out of the hero's layout: it appears and goes without moving
    // anything, and the hero's height never depends on it.
    BorderSurface {
      visible: root.liveState !== ""
      anchors.right: powerSwitch.left
      anchors.rightMargin: Style.space(8)
      anchors.verticalCenter: heroLabels.verticalCenter
      implicitWidth: statePill.implicitWidth + Style.space(10)
      implicitHeight: statePill.implicitHeight + Style.space(4)
      color: "transparent"
      borderSpec: Border.controlSpec("normal", root.foreground, Commons.Color.accent)
      radius: Style.cornerRadius

      Text {
        id: statePill
        textFormat: Text.PlainText
        anchors.centerIn: parent
        text: root.liveState
        color: heroRoot.heroDim
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        font.bold: true
      }
    }
  }

  // "Language            English  ›" — opens that setting's choice page.
  component SettingRow: CursorSurface {
    id: settingRow
    property string rowId: ""
    property string label: ""
    property string value: ""
    property bool warning: false

    width: parent ? parent.width : implicitWidth
    hasCursor: root.currentRow === rowId
    foreground: root.foreground
    implicitHeight: settingContent.implicitHeight + Style.spacing.rowPaddingX

    MouseArea {
      anchors.fill: parent
      hoverEnabled: true
      cursorShape: Qt.PointingHandCursor
      onEntered: root.setRowCursor(settingRow.rowId)
      onClicked: root.openPage(settingRow.rowId, true)
    }

    RowLayout {
      id: settingContent
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      anchors.leftMargin: Style.space(10)
      anchors.rightMargin: Style.space(10)
      spacing: Style.space(8)

      Text {
        textFormat: Text.PlainText
        text: settingRow.label
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.body
      }

      Text {
        textFormat: Text.PlainText
        Layout.fillWidth: true
        horizontalAlignment: Text.AlignRight
        text: settingRow.value
        color: settingRow.warning ? root.urgent : root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.body
        elide: Text.ElideRight
      }

      Text {
        textFormat: Text.PlainText
        text: "›"
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.body
      }
    }
  }

  component BackRow: CursorSurface {
    id: backRow
    hasCursor: root.cursorActive && root.page !== "" && root.rowIndex < 0
    foreground: root.foreground
    implicitHeight: backContent.implicitHeight + Style.spacing.rowPaddingX

    MouseArea {
      anchors.fill: parent
      hoverEnabled: true
      cursorShape: Qt.PointingHandCursor
      onEntered: { root.cursorActive = true; root.rowIndex = -1 }
      onClicked: root.leavePage(true)
    }

    RowLayout {
      id: backContent
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      anchors.leftMargin: Style.space(10)
      anchors.rightMargin: Style.space(10)
      spacing: Style.space(8)

      Text {
        textFormat: Text.PlainText
        text: "‹"
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.body
      }

      Text {
        textFormat: Text.PlainText
        Layout.fillWidth: true
        text: root.titleOf(root.page)
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.body
        font.bold: true
        elide: Text.ElideRight
      }
    }
  }

  component OptionRow: CursorSurface {
    id: optionRow
    property var option: null
    property int optionIndex: 0
    readonly property string optionValue: option ? String(option.value) : ""
    readonly property bool selected: optionValue === root.valueOf(root.page)

    hasCursor: root.cursorActive && root.page !== "" && root.rowIndex === optionIndex
    foreground: root.foreground
    implicitHeight: optionContent.implicitHeight + Style.spacing.rowPaddingX

    MouseArea {
      anchors.fill: parent
      hoverEnabled: true
      cursorShape: Qt.PointingHandCursor
      onEntered: { root.cursorActive = true; root.rowIndex = optionRow.optionIndex }
      onClicked: root.choose(optionRow.optionValue, true)
    }

    RowLayout {
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      anchors.leftMargin: Style.space(10)
      anchors.rightMargin: Style.space(10)
      spacing: Style.space(8)

      Text {
        textFormat: Text.PlainText
        Layout.preferredWidth: Style.space(14)
        text: optionRow.selected ? "" : ""
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.bodySmall
        Layout.alignment: Qt.AlignVCenter
      }

      ColumnLayout {
        id: optionContent
        Layout.fillWidth: true
        spacing: Style.space(1)

        Text {
          textFormat: Text.PlainText
          Layout.fillWidth: true
          text: optionRow.option ? String(optionRow.option.label) : ""
          color: root.foreground
          font.family: root.fontFamily
          font.pixelSize: Style.font.body
          font.bold: optionRow.selected
          elide: Text.ElideRight
        }

        Text {
          textFormat: Text.PlainText
          Layout.fillWidth: true
          visible: text !== ""
          text: optionRow.option && optionRow.option.caption ? String(optionRow.option.caption) : ""
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          elide: Text.ElideRight
        }
      }
    }
  }

  component LastDictation: CursorSurface {
    id: lastRow
    hasCursor: root.currentRow === "last"
    foreground: root.foreground
    implicitHeight: lastContent.implicitHeight + Style.spacing.rowPaddingX * 2

    MouseArea {
      anchors.fill: parent
      hoverEnabled: true
      cursorShape: Qt.PointingHandCursor
      onEntered: root.setRowCursor("last")
      onClicked: sw.copyLast()
    }

    ColumnLayout {
      id: lastContent
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      anchors.leftMargin: Style.space(10)
      anchors.rightMargin: Style.space(10)
      spacing: Style.space(4)

      Text {
        textFormat: Text.PlainText
        Layout.fillWidth: true
        text: sw.last ? sw.last.text : ""
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.body
        wrapMode: Text.WordWrap
        maximumLineCount: 3
        elide: Text.ElideRight
      }

      RowLayout {
        Layout.fillWidth: true
        spacing: Style.space(8)

        Text {
          textFormat: Text.PlainText
          Layout.fillWidth: true
          text: [Model.statsLine(sw.last), sw.last ? Model.ago(sw.last.createdAt, root.nowSec) : ""]
                  .filter(function (part) { return part !== "" }).join(" · ")
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          elide: Text.ElideRight
        }

        Text {
          textFormat: Text.PlainText
          text: sw.copied ? "Copied" : "C copy"
          // Faded rather than hidden, so its room is always kept.
          opacity: lastRow.hasCursor || sw.copied ? 1 : 0
          color: sw.copied ? root.foreground : root.dim
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
        }
      }
    }
  }

  component ActionRow: CursorSurface {
    id: actionRow
    property string rowId: ""
    property string glyph: ""
    property string label: ""
    property string caption: ""
    property string hint: ""
    // Opens something further, drawn like the setting rows' chevrons.
    property bool chevron: false

    width: parent ? parent.width : implicitWidth
    hasCursor: root.currentRow === rowId
    foreground: root.foreground
    implicitHeight: actionContent.implicitHeight + Style.spacing.rowPaddingX

    MouseArea {
      anchors.fill: parent
      hoverEnabled: true
      cursorShape: Qt.PointingHandCursor
      onEntered: root.setRowCursor(actionRow.rowId)
      onClicked: root.activate(actionRow.rowId)
    }

    RowLayout {
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      anchors.leftMargin: Style.space(10)
      anchors.rightMargin: Style.space(10)
      spacing: Style.space(8)

      Text {
        textFormat: Text.PlainText
        text: actionRow.glyph
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.icon
        Layout.alignment: Qt.AlignVCenter
      }

      ColumnLayout {
        id: actionContent
        Layout.fillWidth: true
        spacing: Style.space(1)

        Text {
          textFormat: Text.PlainText
          Layout.fillWidth: true
          text: actionRow.label
          color: root.foreground
          font.family: root.fontFamily
          font.pixelSize: Style.font.body
          elide: Text.ElideRight
        }

        Text {
          textFormat: Text.PlainText
          Layout.fillWidth: true
          visible: actionRow.caption !== ""
          text: actionRow.caption
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          elide: Text.ElideRight
        }
      }

      Text {
        textFormat: Text.PlainText
        visible: actionRow.hint !== ""
        text: actionRow.hint
        color: root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        font.bold: true
        Layout.alignment: Qt.AlignVCenter
      }

      Text {
        textFormat: Text.PlainText
        visible: actionRow.chevron
        text: "\u203a"
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.body
        Layout.alignment: Qt.AlignVCenter
      }
    }
  }
}
