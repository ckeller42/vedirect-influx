API reference
=============

Generated from the docstrings. The optional runtime libraries (serial, InfluxDB client, BLE,
D-Bus) are mocked for the build. ``vedirect_influx.vreglink_service`` is not listed: it imports
the Pi-only D-Bus stack and is described in :doc:`../vcr-component-assembly-scope`.

Configuration and entry point
-----------------------------

.. automodule:: vedirect_influx.config

.. automodule:: vedirect_influx.cli

Sources
-------

.. automodule:: vedirect_influx.reader

.. automodule:: vedirect_influx.ble

Decoders
--------

.. automodule:: vedirect_influx.text

.. automodule:: vedirect_influx.protocol

.. automodule:: vedirect_influx.history

Sinks
-----

.. automodule:: vedirect_influx.sinks.base

.. automodule:: vedirect_influx.sinks.influx

.. automodule:: vedirect_influx.sinks.vrm

.. automodule:: vedirect_influx.sinks.stdout

.. automodule:: vedirect_influx.sinks.multi

VRM client
----------

.. automodule:: vedirect_influx.vrm

VReg IPC
--------

.. automodule:: vedirect_influx.ipc

.. automodule:: vedirect_influx.vreglink
