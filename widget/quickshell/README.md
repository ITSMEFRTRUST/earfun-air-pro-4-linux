# Quickshell bar widget

A bar module and popup for the earfun daemon. The module shows a battery donut and the noise mode.
The popup shows battery per bud and case, the noise switch, EQ, settings and gestures. Settings not
verified on real buds carry a small dot, and a SET the daemon refuses locks its control.

Needs [Quickshell](https://quickshell.org) (tested with 0.3.2), a running `earfun` daemon, and a Nerd
Font (JetBrainsMono Nerd Font by default, change it in `Theme.qml`). `notify-send` is used for errors.

The widget runs `earfun` from `PATH`. If `~/.local/bin` isn't on the `PATH` your shell starts with,
set `EARFUN_BIN` to the full path.

## Run it on its own

This shows a small pill in the top-right corner of each screen, on top of whatever is there:

```
qs -p widget/quickshell
```

The pill is hidden while the daemon isn't running. Click it for the popup. Right-click or scroll
changes the noise mode.

## Add it to your own Quickshell bar

1. Copy `Theme.qml`, `Popups.qml`, `PopupLayer.qml`, `modules/` and `popups/` into your config. If
   you already have a `Theme` or `Popups` singleton, rename these or merge them.
2. Add one popup layer per screen in your `shell.qml`:

   ```qml
   Variants { model: Quickshell.screens; PopupLayer {} }
   ```

3. Put the module in your bar, with `import "modules"`. `x` is relative to the window, so this
   assumes a full-width bar. This path has not been tested outside the author's own bar:

   ```qml
   Earbuds {
       onClicked: (button, x) => Popups.toggle(screen.name, x)
   }
   ```

`tip` and `hovered` on the module are there if your bar shows tooltips.

## Super+N in Hyprland

```
bind = SUPER, N, exec, ~/.local/bin/earfun mode cycle
```

This goes off, ANC, ambient, off. The widget follows, because it watches the daemon's state.

## IPC

If the widget runs in your main Quickshell config, leave out `-p`:

```
qs -p widget/quickshell ipc call earbuds cycle
qs -p widget/quickshell ipc call earbuds state
qs -p widget/quickshell ipc call earbudspopup toggle    # only in the standalone shell.qml
```

## Try it without buds

```
bin/earfun --socket /tmp/earfun-test.sock daemon --fake
EARFUN_SOCK=/tmp/earfun-test.sock EARFUN_BIN="$PWD/bin/earfun" qs -p widget/quickshell
```
