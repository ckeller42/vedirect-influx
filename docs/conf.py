"""Sphinx configuration for vedirect-influx.

Markdown pages (MyST) with Mermaid diagrams, an autodoc API page, and the Furo theme.
Optional runtime dependencies are mocked, so the build needs only ``docs/requirements.txt``.
"""

import os
import sys

# repo root on the path so autodoc can import vedirect_influx.*
sys.path.insert(0, os.path.abspath(".."))

project = "vedirect-influx"
author = "ckeller42"
copyright = "ckeller42, MIT License"

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinxcontrib.mermaid",  # client-side mermaid.js, no Java and no server
    "myst_parser",
]

# ```mermaid fences render through sphinxcontrib.mermaid; heading anchors make the
# `page.md#section` links used across the pages (and the README) resolve.
myst_fence_as_directive = ["mermaid"]
myst_heading_anchors = 3

# autodoc must not need the runtime stack (hardware and network libraries, Pi-only D-Bus).
autodoc_mock_imports = [
    "serial",
    "influxdb_client",
    "yaml",
    "bleak",
    "victron_ble",
    "dbus",
    "gi",
]
autodoc_default_options = {"members": True, "undoc-members": False}

html_theme = "furo"
html_title = "vedirect-influx"
html_theme_options = {
    "source_repository": "https://github.com/ckeller42/vedirect-influx",
    "source_branch": "main",
    "source_directory": "docs/",
}

# docs/superpowers/ holds local-only design records (gitignored); never part of the site.
exclude_patterns = ["_build", "superpowers/**"]
