# Glossary

```{glossary}
:sorted:

VE.Direct
  Victron's serial interface: a text stream plus the HEX command protocol.

HEX protocol
  Request and response frames starting with a colon. Here only Get is used.

Register
  A numbered value in the charger. The daily history is `0x1050` to `0x106D`.

Instant Readout
  Victron's encrypted Bluetooth advertisement with live values.

Smart Battery Sense
  Victron BLE battery temperature and voltage sensor.

VRM
  Victron Remote Management, the web portal and app.

Portal ID
  The VRM installation identifier, here the ethernet MAC without colons.

GX device
  Victron's controller (Cerbo, Venus OS). The VRM sink presents as one.

VictronConnect-Remote
  Configuring a charger through VRM, needs genuine Venus OS.

VReg
VregLink
  Victron register access, and its D-Bus interface used by VictronConnect-Remote.

Sink
  A destination for decoded data, see `Sink`.
```
