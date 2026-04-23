import QtQuick
import QtQuick.Window

Window {
    id: root
    width: 380
    height: 92
    visible: hudController.hudVisible
    color: "transparent"
    title: "Audio HUD Overlay"

    flags: Qt.FramelessWindowHint
         | Qt.WindowStaysOnTopHint
         | Qt.Tool
         | Qt.WindowTransparentForInput

    Rectangle {
        anchors.fill: parent
        radius: 18
        color: hudController.mutedActive ? "#D6401016" : "#D20A0C12"
        border.width: 1
        border.color: hudController.mutedActive ? "#E6FF6262" : "#DC80AAFF"

        Text {
            anchors.centerIn: parent
            text: hudController.hudText
            color: "#F4F7FF"
            font.family: "Noto Sans"
            font.pixelSize: 26
            font.bold: true
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
        }
    }
}

