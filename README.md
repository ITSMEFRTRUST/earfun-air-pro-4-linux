# EarFun Air Pro 4 on Linux

An unofficial Linux controller for the EarFun Air Pro 4 earbuds. It changes noise mode, codec and
audio mode, and shows battery, without the phone app. There is a background daemon, a command line
tool, an optional Quickshell bar widget, and a small service that repairs broken audio after a bud
goes back in the case.

> Read [DISCLAIMER.md](DISCLAIMER.md) first. This is not an EarFun product. Sending commands to the
> buds could misconfigure them.

**Tested only on the author's own Air Pro 4 (firmware `TW600-3091_20250919_v0.4.1`) on Arch Linux.**
It may behave differently on other firmware, and it is not written for other EarFun models.

The protocol work comes from [Gadgetbridge](https://codeberg.org/Freeyourgadget/Gadgetbridge), not
from me: its EarFun code was ported to Python here, then the parts below were checked against real
buds. Captures from [omarchy-headphones](https://github.com/ncr/omarchy-headphones) helped too. See
[THIRD_PARTY.md](THIRD_PARTY.md). Built with help from Claude.

## Features

- Noise mode: off, ANC, ambient, or cycle through them
- Battery for left bud, right bud and case, including the last known case level
- Audio codec and LE Audio / Fast Pair mode
- Live state as JSON lines, for widgets and scripts
- Quickshell bar module and popup
- A service that reconnects the buds when their audio breaks while they stay connected
- Fake buds, so you can run the tests and work on widgets with no hardware

## What works and what doesn't

| | Status |
|---|---|
| Set noise mode (`mode`) | Verified on real buds |
| Set `advanced_audio` (LE Audio / Fast Pair) | Verified on real buds |
| Set `audio_codec` | Verified on real buds |
| Read battery, firmware, mode | Verified on real buds |
| EQ, tap gestures | Written but untested, refused by default |
| All other settings | Ported from Gadgetbridge, never sent to real buds, refused by default |
| Bud swap fix (below) | Rests on one real swap, so treat it as promising, not proven |
| iPhone | Not possible: Apple blocks that connection type |
| Firmware updates | Not supported, you still need the official app |

Refused means the daemon won't send it unless you start it with `--allow-unverified-sets`. That flag
also unlocks things like `factory_reset`, so only use it if you accept the risk.

## Requirements

- Linux with BlueZ and PipeWire / WirePlumber
- Python 3, `python-dbus`, `python-gobject`
- `bluetoothctl`, for the heal service
- Buds already paired through your normal Bluetooth tools

On Arch:

```
sudo pacman -S python python-dbus python-gobject bluez bluez-utils
```

## Install

Clone this repository wherever you like, then, from inside it:

```
git clone https://github.com/ITSMEFRTRUST/earfun-air-pro-4-linux
cd earfun-air-pro-4-linux
mkdir -p ~/.local/bin ~/.config/systemd/user
ln -s "$PWD/bin/earfun" "$PWD/bin/earfun-audio-heal" ~/.local/bin/
ln -s "$PWD/systemd/earfun.service" "$PWD/systemd/earfun-audio-heal.service" ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now earfun earfun-audio-heal
```

The units start the programs from `~/.local/bin`, so they keep working from any clone location. If
you move the clone, redo the `ln` lines with `ln -sf`.

The heal service also reads the system journal, so your user needs access to it. On most systems
that means being in the `systemd-journal` group.

Only one program can hold the buds' control channel, so stop anything else that uses it first.

## Usage

Make sure `~/.local/bin` is on your `PATH`.

```
earfun status [--json]
earfun mode off|anc|ambient|cycle [--wait]
earfun get <key> [--cached]
earfun set <key> <value> [--wait]
earfun keys [--json]          # every setting, and which ones are verified
earfun watch                  # JSON lines, for widgets
earfun daemon [--fake] [--address XX:XX:XX:XX:XX:XX] [--allow-unverified-sets] [-v]
```

Exit codes: `0` ok, `1` error or refused (message on stderr), `2` daemon not running.

Without `--address`, the daemon uses the first paired device with "EarFun" in its name that offers
the SPP profile, preferring one that is connected.

After changing the codec, disconnect and reconnect the buds once so the computer picks up the new
codec. The heal service may also react once to a deliberate codec change. That is harmless.

`find_device` plays a loud sound in the buds. Never send it while wearing them.

### Try it without buds

```
bin/earfun --socket /tmp/earfun-test.sock daemon --fake
bin/earfun --socket /tmp/earfun-test.sock status     # in another terminal
```

### Tests

```
python3 -m unittest discover -s tests
```

The tests use the fake buds and never touch real Bluetooth.

### Lower-level tools

Both take the address as an argument and need the daemon stopped first.

- `python3 probe.py XX:XX:XX:XX:XX:XX` sends read-only requests and prints the raw replies.
- `python3 modetest.py XX:XX:XX:XX:XX:XX` changes the noise mode (ANC, ambient, off), reads it back
  each time, and leaves the buds on off.

## The bar widget

[widget/quickshell/](widget/quickshell/) has a [Quickshell](https://quickshell.org) bar module and
popup, with battery, noise mode, codec and settings. Settings not verified on real buds carry a small
dot, and refused ones lock. Setup and an example `Super+N` Hyprland bind are in
[its README](widget/quickshell/README.md).

## Bud swap and the heal service

With `advanced_audio` on `le_audio`, the buds dropped the connection when one went back in the case
and came out again, and sound could stop until they were reconnected. Turning LE Audio off kept the
link up in the one real swap tried:

```
earfun set advanced_audio fast_pair
```

The Fast Pair battery stream, the main source of the case level, also only exists in this mode. You may need to re-pair the buds after changing
it. That has not been confirmed either way.

`earfun-audio-heal` is the backup. When the journal shows the buds' audio failing while they stay
connected, it runs `bluetoothctl disconnect` and `connect`. It makes at most 3 reconnects per
incident (an incident ends after 60 s without new errors) and 6 per 10 minutes.

It finds the buds from `$EARFUN_MAC`, otherwise from BlueZ using the same rule as the daemon. If it
finds none, it logs why, does nothing, and checks again every 30 seconds. To set the address yourself:

```
systemctl --user edit earfun-audio-heal
# [Service]
# Environment=EARFUN_MAC=XX:XX:XX:XX:XX:XX
```

To replay log lines without touching anything: `DRY_RUN=1 EARFUN_MAC=XX:XX:XX:XX:XX:XX bin/earfun-audio-heal --stdin`.

## More detail

[docs/reference.md](docs/reference.md) covers daemon behaviour, the JSON and socket interface, the
wire format, and the full command table with where each command came from.

## Licence

GNU Affero General Public License v3.0, see [LICENSE](LICENSE). The licence comes from the Gadgetbridge
code this is ported from. Third-party credits are in [THIRD_PARTY.md](THIRD_PARTY.md).
