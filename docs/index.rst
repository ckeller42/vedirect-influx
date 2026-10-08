vedirect-influx
===============

``vedirect-influx`` reads a Victron solar charger, both its live telemetry and the
daily history stored on the device, and writes it to InfluxDB for Grafana, optionally also to
the Victron VRM Portal. The charger is reached over the VE.Direct serial port (text stream plus
the read-only HEX protocol) or over Bluetooth Instant Readout. The project is read-only toward
the charger: it never writes a setting.

.. toctree::
   :maxdepth: 1
   :caption: Getting started

   getting-started

.. toctree::
   :maxdepth: 1
   :caption: How-to guides

   howto-deploy

.. toctree::
   :maxdepth: 1
   :caption: Reference

   reference/configuration
   reference/cli
   reference/data-contract
   reference/glossary
   VRM
   reference/api

.. toctree::
   :maxdepth: 1
   :caption: Explanation

   architecture
   vcr-component-assembly-scope
