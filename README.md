# TxBridge

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/screenshots/live-dark.png">
  <img alt="TxBridge live view with six channel bars, two stick boxes and a ten second trace" src="docs/screenshots/live-light.png">
</picture>

TxBridge connects a FlySky FS-CT6A/B class transmitter to a flight simulator on Windows. Plug the radio into the PC with its USB trainer cable and the sticks show up in the simulator as a game controller. It also reads and edits the settings stored inside the radio, which is what the manufacturer's Digital Radio program was for.

It works with the FS-CT6A and CT6B and their rebadges (HK-T6A, Turborix, Exceed, Storm ST-06TX and similar).

## Status

The app and protocol test suite include a software radio. A read-only smoke test has also succeeded on Windows with a real FS-CT6B: TxBridge received live channel frames and read the radio's settings over its USB-serial cable. Radio-setting writes and calibration have not been tested on hardware. `docs/PROTOCOL.md` says which parts of the protocol are verified and which are inferred; hardware reports from other radios and cables are welcome.

## Install

Download `TxBridge-Setup-x.y.z.exe` from the [releases page](../../releases) and run it. There is also a portable zip: unpack it anywhere and TxBridge keeps its settings in a `data` folder next to the program.

Windows may show a SmartScreen warning because the installer is not code-signed yet. The release includes `SHA256SUMS.txt` if you want to check your download.

### Drivers

Open the **Setup** page. It shows what is present and what is missing:

- **Radio cable.** The cable appears as a serial port. Windows usually installs its driver on its own. If no port shows up, Setup links to the driver pages for the common chips (Prolific PL2303, WCH CH340, Silicon Labs CP210x, FTDI).
- **vJoy.** Needed to present the sticks to a simulator. Press Install and TxBridge downloads the installer from the [vJoy releases](https://github.com/njz3/vJoy/releases) and starts it. Windows asks for administrator permission and the installer's own window opens; nothing is installed silently.
- **ViGEmBus.** Optional. Only needed if a simulator insists on an Xbox 360 controller. The [project](https://github.com/nefarius/ViGEmBus) is retired, but its final release still works.

Downloads come from GitHub over HTTPS. For the versions TxBridge was written against, the file's SHA-256 has to match a pinned value. A newer release is accepted only if Windows reports a valid digital signature on it. Otherwise TxBridge refuses to run it and points you at the release page.

## Using it

1. Connect the radio and press **Connect**. No radio yet? **Demo radio** is a software radio you can drag around, so you can set everything up before the cable arrives.
2. **Live** shows the six channels. The marks on each bar are the lowest and highest values seen since the last reset.
3. **Simulator**: pick vJoy, press Start sending, and map the channels to axes. Use Sweep to move one axis end to end while the simulator's control screen is waiting for input. Learn range measures how far your sticks really travel, in software, without touching the radio.
4. A profile can name the programs it belongs to (for example `Liftoff.exe`) and TxBridge switches to it when one starts.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/screenshots/simulator-dark.png">
  <img alt="Simulator page with axis mapping" src="docs/screenshots/simulator-light.png">
</picture>

### Editing the radio

The **Radio** page edits everything stored in the transmitter: model type, stick mode, reverse, end points, subtrim, dual rates, throttle and pitch curves, the three mixes, switches and variables. A field you have changed gets a blue outline until it is sent. Press **Send to radio** (or switch to Auto), and TxBridge reads the settings back to confirm the radio took them. A copy of what was in the radio is saved to the library before every send.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/screenshots/radio-curves-dark.png">
  <img alt="Throttle and pitch curve editors with an edited point" src="docs/screenshots/radio-curves-light.png">
</picture>

The **Library** keeps models you have saved, with search, tags, compare and load-and-send. Models export to `.cfg` (the format t6config uses), CSV, XLSX and PDF, and the whole library can be backed up and restored.

## Build from source

You need Python 3.10 or newer.

```
pip install -r requirements.txt
python run_txbridge.py --demo
```

The Xbox 360 output needs `pip install -r requirements-xbox.txt` on Windows. On Linux, TxBridge can use uinput (`pip install evdev`).

To build the Windows program, installer and portable zip:

```
build_windows.bat
```

That script needs [Inno Setup 6](https://jrsoftware.org/isdl.php) for the installer; without it you still get the program folder and the zip. Pushing a tag like `v1.1.0` makes GitHub Actions do the same and attach the files to a release. Run the tests with `pytest`.

## How it was made

The serial protocol was worked out by analysing how the Digital Radio demo exchanges data with the transmitter: frame format, checksums, the settings layout and value ranges. No code, artwork or licence logic from that program is used. See [NOTICE](NOTICE) and `docs/PROTOCOL.md`.

## License

MIT, see [LICENSE](LICENSE).
