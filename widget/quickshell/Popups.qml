pragma Singleton
import QtQuick
import Quickshell

// Whether the earbuds popup is open, on which output, and where it should sit.
Singleton {
    property bool open: false
    property string screen: ""      // output name it is on
    property real anchorX: -1       // screen x to centre it under (-1 = middle)

    function toggle(screenName, x) {
        if (open && screen === screenName) {
            close();
            return;
        }
        anchorX = x ?? -1;
        screen = screenName;
        open = true;
    }

    function close() { open = false; }
}
