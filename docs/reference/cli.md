# Command-line reference

The package installs two console scripts, defined in
[`pyproject.toml`](https://github.com/ckeller42/vedirect-influx/blob/main/pyproject.toml).

## `vedirect-influx`

```text
vedirect-influx [-h] [--config CONFIG] [--history-once] [--test] [-v]
                [{run,history-once,vrm-register}]
```

| Option | Meaning |
| --- | --- |
| `command` | `run` (default), `history-once` or `vrm-register` |
| `--config`, `-c` | Path to the [YAML config](configuration.md). Without it, the defaults apply |
| `--history-once` | Alias for the `history-once` command |
| `--test` | With `vrm-register`: send a connectivity ping only |
| `-v`, `--verbose` | Debug logging. Logs go to stderr as `time level message` |

### `run` (default)

Builds the sinks from `sink:` (plus VRM when `vrm.enabled`), builds the reader for `source`, and
runs forever. With `source: serial` and `vreg.ipc_enabled: true` it also starts the VReg IPC
server. It runs until stopped, and the sinks are closed on the way out.

Exits at start with a message when the sink type is unknown, when the InfluxDB token variable is
empty, or (BLE) when no device or key is configured.

### `history-once`

Opens the serial port, reads all 30 daily-history registers once, writes the populated days to
the sinks, prints `wrote N day records` and exits. Use it as a smoke test and to backfill. It
works with `source: serial` only: with `source: ble` it exits non-zero before touching any
device, because Instant Readout carries no history. Stop the running service first, since only
one process may own the port.

### `vrm-register`

Registers the install with the VRM Portal. It derives the Portal ID, creates the auth token file
if it does not exist (mode `0600`) and sends an `ANNOUNCE`; on success it prints the Portal ID and
the claim steps. With `--test` it sends a `TEST_POST` and prints `vrm: OK` or an error. Exit
status is 0 on success and 1 otherwise. Sequence and protocol: [VRM upload protocol](../VRM.md).

## `vedirect-influx-vreglink`

The experimental VictronConnect-Remote D-Bus service (Linux only, needs the `vcr` extra). It
registers `com.victronenergy.solarcharger.buspi` and forwards `GetVreg` calls to the reader's IPC
socket. It is dormant, see [VictronConnect-Remote scope](../vcr-component-assembly-scope.md).

| Option | Default | Meaning |
| --- | --- | --- |
| `--socket` | `/run/vedirect-influx/vreg.sock` | Reader IPC socket |
| `--product-id` | `0xA075` | Product ID announced on D-Bus |
| `--custom-name` | `BusPi 75/15` | Device name announced on D-Bus |
