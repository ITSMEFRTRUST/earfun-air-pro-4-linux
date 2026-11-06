# Third-party credits

This project is licensed under the AGPL-3.0 ([LICENSE](LICENSE)). It builds on the work below.

## Gadgetbridge

- **Source:** <https://codeberg.org/Freeyourgadget/Gadgetbridge>, commit
  `edbea98cbe1377001c0b8154ac20cb930e1db7f6`
- **Licence:** AGPL-3.0 (its `LICENSE` file and the "Code Licenses" section of its README)
- **What came from it:** nearly all of the protocol knowledge in `earfun/protocol.py`, ported to
  Python from `app/src/main/java/nodomain/freeyourgadget/gadgetbridge/service/devices/earfun/` and
  its resources. That covers the frame layout, command numbers, setting values, gesture and EQ
  encoding, and EQ presets. `earfun/fake.py` follows the same encoding. Each entry's source is listed
  in [docs/reference.md](docs/reference.md) and in `earfun keys`.

## omarchy-headphones

- **Source:** <https://github.com/ncr/omarchy-headphones>, in particular
  [pull request #30](https://github.com/ncr/omarchy-headphones/pull/30), merge commit
  `2a7d06d1ddf651022c96fc8cd4011192110373ed`
- **Licence:** MIT, full text below
- **What came from it:** the capture `docs/captures/earfun-air-pro-4.txt`, used to model the fake
  buds' behaviour in `earfun/fake.py` (reply shapes and unsolicited frames, including the `0358` frame
  values), and as a reference for the mode and battery commands.

```
MIT License

Copyright (c) 2026 Jacek Becela

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## Used at runtime, not included here

Python, dbus-python, PyGObject, BlueZ, WirePlumber, and for the widget Quickshell, Qt and a Nerd Font
(JetBrainsMono Nerd Font by default). You install these yourself, and each has its own licence.
