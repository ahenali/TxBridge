# Contributing

Bug reports and hardware reports are the most useful thing you can send. Code is welcome too.

## Reports from real radios

The protocol was recovered from a demo program, not from documentation, and TxBridge has so far only been run against a simulated radio. If you have an FS-CT6A/B (or a rebadge), the [hardware report](.github/ISSUE_TEMPLATE/hardware_report.md) template tells you what to check. `docs/PROTOCOL.md` lists which parts are verified and which are guesses. Confirming or correcting the guesses helps more than anything else.

When something misbehaves, open Tools > Diagnostics, reproduce it, and attach the log.

## Working on the code

```
python -m venv .venv
.venv\Scripts\activate          # or: source .venv/bin/activate
pip install -r requirements-dev.txt
python run_txbridge.py --demo   # a software radio, no hardware needed
pytest
```

Tests run without a display (`QT_QPA_PLATFORM=offscreen`, set for you in `tests/conftest.py`).

A few things worth knowing:

- Protocol bytes live in `txbridge/protocol.py`. `tests/test_protocol.py` keeps an independent copy of the byte map, so a change has to be made in both places on purpose.
- The interface is plain Qt widgets with one stylesheet in `txbridge/ui/theme.py`. Use the colour tokens in `T`, not literal colours.
- `tests/test_layout.py` renders every page at several sizes and fails on clipped text. If it fails after a change, the layout is wrong, not the test.
- `python tools/screenshots.py` regenerates the README images.

## Pull requests

Keep them small and say what you tested. If you could not test on Windows or on a real radio, say so.
