import QtQuick

// Stands in for qs.Ui's KeyboardPanel in the harness. The real one is a layer
// shell window, which needs a Wayland compositor; the bar widget's logic does
// not, so the harness gives its content a plain Item to live in instead. Same
// properties and sizing helpers the widget uses, nothing else.
Item {
  id: root
  required property Item anchorItem
  required property QtObject bar
  property var owner: null
  property bool open: false
  property bool centerOnBar: false
  property Item focusTarget: null
  property int contentWidth: 280
  property int contentHeight: 200
  width: contentWidth
  height: contentHeight
  default property alias contentItem: contentHolder.children

  function fittedContentWidth(width, cap) {
    var desired = Math.max(1, Number(width) || 1)
    return Math.round(cap !== undefined && Number(cap) > 0 ? Math.min(desired, Number(cap)) : desired)
  }
  function fittedContentHeight(implicitHeight, cap) {
    var desired = Math.max(1, Number(implicitHeight) || 1)
    return Math.round(cap !== undefined && Number(cap) > 0 ? Math.min(desired, Number(cap)) : desired)
  }

  Item {
    id: contentHolder
    anchors.fill: parent
  }
}
