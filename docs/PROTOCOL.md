# Radio protocol (FS-CT6A/B family, USB trainer cable)

Recovered from the Digital Radio 1.0.4 demo (a .NET assembly with renamed symbols and an
encrypted string table). The string table was decrypted offline to recover the enumerations and the
column names that tie every settings byte to a parameter name. `tests/test_protocol.py` contains the
byte map written out a second time, independently of `protocol.py`, and checks both agree on random data.

## Link
115200 baud, 8N1, USB-serial cable (Prolific PL2303 class). Multi-byte values are big-endian.
Checksum = 16-bit sum of the data bytes between the type byte and the checksum.

## Radio to PC
| Frame | Length | Layout |
|---|---|---|
| Live | 18 | `55 FC` + 6 x u16 pulse width (µs) + u16 aux + u16 sum(bytes 2..15) |
| Settings | 69 | `55 FD` + 65 byte payload + u16 sum(bytes 2..66) |

## PC to radio
| Packet | Bytes |
|---|---|
| Read settings | `55 FA 00` (radio answers with a Settings frame) |
| Write settings | `55 FF` + 65 byte payload + u16 sum |
| Enter calibration | `55 88` |
| Leave calibration | `55 99` |

## Settings payload (frame byte numbers; payload index = byte - 2)
| Byte | Meaning | Type |
|---|---|---|
| 2 | high nibble stick mode (0-3 = Mode 1-4), low nibble model type (0 Acro, 1 Heli 120, 2 Heli 90, 3 Heli 140) | nibbles |
| 3 | bits 0-5 = CH1-6 direction; **bit set = normal, clear = reverse**. Bits 6-7 unknown, preserved | bits |
| 4-9 | dual rate CH1 on/off, CH2 on/off, CH4 on/off (0-100) | u8 |
| 10-12 | swash AFR CH1, CH2, CH6 (-100..100) | s8 |
| 13-24 | end points CH1 min/max ... CH6 min/max (0-120) | u8 |
| 25-34 | throttle curve P1-P5, interleaved normal, idle, normal, idle... (-100..100) | s8 |
| 35-44 | pitch curve P1-P5, interleaved normal, idle (-100..100) | s8 |
| 45-50 | subtrim CH1-6 (-120..120) | s8 |
| 51-54, 55-58, 59-62 | mix 1-3: source (high nibble) / destination (low nibble), up rate, down rate, switch | u8, s8, s8, u8 |
| 63, 64 | switch A, B: 0 none, 1 dual rate, 2 throttle cut, 3 normal/idle | u8 |
| 65, 66 | variable A, B: 0 none, 1 pitch adjust | u8 |

Mix source: 0-5 = CH1-6, 6 = variable A, 7 = variable B. Destination: 0-5 = CH1-6. Mix switch: 0 A, 1 B, 2 on, 3 off.

`.cfg` files are the 65 payload bytes followed by the u16 checksum (67 bytes).

## What is verified and what is inferred
Verified directly from the binary: framing, checksums, every offset, nibble/bit packing, signedness,
enumeration values and valid ranges, the three command bytes `FA 00`, `FF`, `88`, the 115200 baud rate,
vJoy axis usage (X,Y,Z,Rx,Ry,Rz). A read-only smoke test on a real FS-CT6B over a CP210x USB-serial
cable received live frames and a settings reply. No settings writes or calibration commands were sent.

Inferred, not hardware-tested:
* `99` ends calibration. The demo's Start-calibration handler sends `88`; the `99` builder exists but its call
  site was removed from the demo, so its role is deduced from the manual and from symmetry.
* Pulse widths are microseconds (the original subtracts 1000 to get 0..1000).
* The two aux bytes at the end of the live frame are unidentified and shown only in diagnostics.
* Stick-mode gimbal layout in the Live view follows the standard Mode 1-4 definitions.
* Continuous live streaming and a settings reply within about a second were observed on one FS-CT6B;
  other radios, rebadges and cables still need hardware reports.
