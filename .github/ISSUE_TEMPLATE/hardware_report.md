---
name: Hardware report
about: Results from a real transmitter
---

Thank you for testing on a real radio. Fill in what you can; partial reports are fine.

**Radio and cable**
- Model and any rebadge name:
- Cable chip (Device Manager > Ports shows the driver name):
- Windows version:

**Checks**
- [ ] Connected and saw live channel values
- [ ] Read the radio's settings
- [ ] Changed one setting, sent it, and the read-back check passed
- [ ] Reverse on a channel matches what the radio's screen or behaviour shows
- [ ] vJoy or Xbox 360 output moved in the simulator or in joy.cpl
- [ ] Calibration (only if you are comfortable with it; it writes to the radio)

**Things the docs say are unconfirmed**
- Are the live values 1000 to 2000 microseconds? How did you check?
- Do the two extra bytes in a live frame change with anything (a switch, battery)?

**Diagnostics log**
Tools > Diagnostics > Save, then attach it.
