# Scope: VictronConnect-Remote via assembled Venus components (no full Venus OS)

**Goal.** Make the SmartSolar 75/15 appear and be usable in **VictronConnect's VRM tab**
(two-way / VC-R) on the existing Raspberry Pi (buspi, aarch64 / Debian 13), **without** replacing
Raspberry Pi OS, and **without** losing the current `vedirect-influx` → InfluxDB → Grafana stack.

**Why this is even plausible.** Investigation (2026-06-03) proved VC-R is *not* gated on genuine GX
hardware — a Raspberry Pi running real Venus OS gets it. The gate is VRM's backend flag
`twoWayCommunication` (→ `hasVictronConnect`), which is earned by running the **genuine Venus MQTT
stack** (FlashMQ + `dbus-flashmq` with the `GXrpc` RPC bridge + the `mqtt-rpc` service), not by any
single replayable signal. None of the device-side signals we could fake flipped it (logging
protocol — no such code; MQTT `VrmPortal=2`; a plain `mosquitto` bridge; correct firmware from
creation). So the only path is to run the *actual* components.

`dbus-flashmq` and FlashMQ are **open source**; `mqtt-rpc` was extracted from a Venus v3.55 image;
`localsettings` is open source. The one piece Venus provides that we must replace is a D-Bus
`solarcharger` service that exposes the MPPT's **`VregLink`** — which we can implement ourselves
because we already speak VE.Direct text + HEX in `vedirect-influx`.

## ⚠️ Milestone 0 — validate the premise before building (do this first)

The entire payoff rests on one **unproven** assumption: that the genuine FlashMQ/`GXrpc` RPC bridge
running on a *Pi* actually flips `twoWayCommunication` in VRM. De-risk it cheaply:

- Flash genuine **Venus OS (Raspberry Pi image)** to a spare SD card, boot buspi from it, move the
  VE.Direct USB cable over.
- Settings → VRM online portal → ensure two-way is on; claim the install.
- Check `vrmapi.victronenergy.com/v2/installations/<id>/system-overview` →
  `twoWayCommunication: true`? VictronConnect VRM tab shows the charger?

If **yes** → the assembly below is worth building (and we'll have a known-good reference to diff
against). If **no** (even genuine Venus-on-Pi can't) → stop; nothing assembled will do better.

## Target architecture (runs alongside the current stack)

```text
            VE.Direct USB (single port)
                     │
        ┌────────────▼─────────────┐
        │  serial owner (ONE only)  │   ← the hard constraint: one process owns the port
        └───────┬───────────┬───────┘
   live values  │           │  on-demand HEX Get/Set (VReg)
                ▼           ▼
   com.victronenergy.solarcharger  (NEW D-Bus service)
     • /Dc/0/Voltage, /Pv/V, /State, …  (live, for telemetry)
     • /Devices/0/VregLink → GetVreg(q)->ay / SetVreg(qay)   (for VC-R)
                │  (system D-Bus)
   ┌────────────┼───────────────────────────────┐
   │            │                                │
   ▼            ▼                                ▼
 localsettings  FlashMQ + dbus-flashmq         mqtt-rpc.py
 (VrmPortal=2)  • N/R/W telemetry → VRM         • subscribes P/<id>/in (local)
                • RPC bridge (GXrpc) ↔          • vreg-device-list / vreg-get-set
                  mqtt-rpc.victronenergy.com      → reads VregLink over D-Bus
                  (P/<id>/in, P/<id>/out)         → answers P/<id>/out
                          │
                          ▼
                    VRM backend sets twoWayCommunication=true → VictronConnect shows the MPPT
   InfluxDB/Grafana: fed as today (see "serial ownership" below)
```

## Components

| Component | Source | Effort |
| --- | --- | --- |
| **FlashMQ** | open source (halfgaar/FlashMQ) | extract prebuilt aarch64 binary from Venus image, or build |
| **dbus-flashmq** | open source (victronenergy/dbus-flashmq), builds against Venus SDK | extract prebuilt `.so` from Venus image, or build (SDK) |
| **localsettings** | open source (victronenergy, Python/velib) | run as-is; set `/Settings/Network/VrmPortal=2` |
| **mqtt-rpc** | extracted from Venus v3.55 (Python + velib + vregops) | run against `localhost:1883`; prune unneeded handlers |
| **VRM registration** | `vedirect_influx.vrm.store_mqtt_password` (we have it) | reuse |
| **`solarcharger` D-Bus service w/ VregLink** | **NEW — core deliverable** | write (reuses our HEX code) |

### The core new code — `VregLink` D-Bus solarcharger service

`mqtt-rpc`'s `vreg-get-set` calls `GetVreg(q)->ay` / `SetVreg(qay)` on
`com.victronenergy.solarcharger.../Devices/0/VregLink`. We provide a D-Bus service that:

- registers `com.victronenergy.solarcharger.<x>` with `/Devices/0`, ProductId `0xA075`, etc.;
- publishes the standard live paths (so `dbus-flashmq` mirrors them as `N/` telemetry);
- implements `VregLink.GetVreg(regid)` by issuing a VE.Direct **HEX `Get`** (cmd 7) to the MPPT and
  returning the raw register bytes — exactly what VictronConnect decodes natively over Bluetooth;
- `SetVreg` initially **read-only** (reject/no-op), matching the tool's design.

We already have the VE.Direct HEX framing in `vedirect-influx` (history reader). This is the piece
that turns "we speak the charger" into "Venus's RPC stack can read the charger."

## The hard constraint: single VE.Direct port

The MPPT has one VE.Direct port; today `vedirect-influx` owns it. The new `solarcharger`/VregLink
service also needs serial access. Two readers can't share the port. Two options:

- **Option A (recommended, lower disruption): `vedirect-influx` stays the serial owner.** Extend it
  with an on-demand `vreg_get(regid)->bytes` (it already switches to HEX for history) exposed over a
  tiny local IPC (Unix socket or D-Bus method). The new `solarcharger` D-Bus service becomes a thin
  proxy: live paths from `vedirect-influx`'s stream, `VregLink` calls forwarded to its IPC.
  InfluxDB/Grafana path is **unchanged**.
- **Option B (cleaner Venus model, more disruption): the new D-Bus service owns the port** and
  `vedirect-influx` is refactored to read from D-Bus/MQTT instead of serial. More faithful but
  touches the working InfluxDB feed.

→ **Recommend Option A** (preserves the current stack, which has been the standing requirement).

## Runtime / packaging

- **Native systemd units** on Pi OS (recommended over containers): all services share the host
  **system D-Bus**, which is simplest. A dedicated dir (`/opt/buspi-vcr/`) + units for FlashMQ,
  localsettings, mqtt-rpc, and the VregLink service. (Containers complicate D-Bus sharing.)
- **Binary compatibility risk:** Venus prebuilt aarch64 binaries (flashmq, dbus-flashmq `.so`)
  target Venus's glibc/toolchain; on Debian 13 (trixie) they may need a compat shim or rebuilding.
  Mitigation: build `dbus-flashmq`/FlashMQ from source against trixie, or run *only* those two in a
  minimal Venus-userland container bridged to the host D-Bus.

## Risks / open questions

1. **(Biggest) `twoWayCommunication` flip is unproven** → Milestone 0 settles it.
2. **`dbus-flashmq` binary vs build** on trixie/aarch64 (glibc).
3. **`mqtt-rpc` Venus assumptions** — it imports velib and may expect services we don't run
   (e.g. `com.victronenergy.system` for `device-list-2`). VC-R likely uses `vreg-device-list` /
   `vreg-get-set`, which need only our solarcharger + VregLink — but this must be confirmed against
   what VictronConnect actually sends (capture on `P/<id>/in` once two-way is live).
4. **RPC bridge auth/clientid** — confirm `dbus-flashmq` uses our `ccgxapikey` creds + `GXrpc`
   prefix (we have the bridge config from the extracted registrator).
5. **Unofficial/undocumented**; personal use only; Victron may change it.

## Phased plan

- **Phase 0 — Validate** (Milestone 0 above): genuine Venus OS on SD → confirm a Pi flips
  `twoWayCommunication` + VC-R works. **Gate: go/no-go.** Capture the real `P/<id>/in` traffic and
  the working `vrm_bridge.conf` as references.
- **Phase 1 — Brokerage up:** run FlashMQ + `dbus-flashmq` + `localsettings(VrmPortal=2)` on buspi;
  confirm telemetry (`N/`) reaches VRM and the RPC bridge connects with our creds.
- **Phase 2 — VregLink service (TDD):** write the `solarcharger` D-Bus service + `vreg_get` HEX
  proxy in `vedirect-influx` (Option A). Unit-test the HEX-Get encoding + VregLink responses against
  fixtures captured in Phase 0.
- **Phase 3 — mqtt-rpc:** run the extracted `mqtt-rpc` against the local broker; answer
  `vreg-device-list` + `vreg-get-set`; verify VictronConnect lists + opens the MPPT.
- **Phase 4 — Harden:** systemd units, coexistence with `vedirect-influx`/InfluxDB, docs, read-only
  enforcement on `SetVreg`.

## Definition of done

VictronConnect (VRM tab) shows **BusPi → SmartSolar 75/15** and opens its live device page; VRM
`system-overview` reports `twoWayCommunication: true`; InfluxDB/Grafana keep updating; everything
runs alongside the current stack on Raspberry Pi OS.
