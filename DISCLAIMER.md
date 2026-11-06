# Disclaimer

## Not affiliated with EarFun

This project is an independent, unofficial effort. It is **not affiliated with, sponsored by, or
endorsed by EarFun.** EarFun and Air Pro are trademarks of their owners and are used here only to say
which hardware this project works with. The project is also not affiliated with Gadgetbridge or
omarchy-headphones, whose work it builds on.

## Interoperability

This project talks to earbuds the user owns, so that they can be used from Linux. Its knowledge of
the protocol comes from Gadgetbridge's published source and from public captures, plus observing how
the author's own buds respond.

## Commands could misconfigure your buds

- Only the `mode`, `advanced_audio` and `audio_codec` SETs were tried on real buds, and only on one
  pair with one firmware version.
- All other SETs, including EQ and gestures, are untested. The daemon refuses them unless you start
  it with `--allow-unverified-sets`.
- That flag also unlocks commands such as `factory_reset`, `reboot`, `power_off`, and `find_device`,
  which plays a loud sound in the buds. Don't send it while wearing them.
- A wrong command could misconfigure the buds or, in the worst case, leave them not working properly.
  Using this software may affect your warranty.

## No warranty: use at your own risk

This software is provided **"AS IS", WITHOUT WARRANTY OF ANY KIND**, express or implied, as stated in
the [LICENSE](LICENSE). You use it at your own risk.
