import QtQuick
import Quickshell
import Quickshell.Io
import qs

// Standalone setup: a small floating pill in the top-right corner plus the popup, one per screen.
// Run with `qs -p widget/quickshell`. To add the module to your own Quickshell bar instead, see README.md.
ShellRoot {
    Variants { model: Quickshell.screens; EarbudsBar {} }
    Variants { model: Quickshell.screens; PopupLayer {} }

    // `qs -p <dir> ipc call earbudspopup toggle`
    IpcHandler {
        target: "earbudspopup"
        function toggle(): void { Popups.toggle(Quickshell.screens[0]?.name ?? "", -1); }
    }
}
