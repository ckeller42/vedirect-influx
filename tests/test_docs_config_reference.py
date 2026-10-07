"""The configuration reference page lists every ``Config`` field."""

import re
from dataclasses import fields
from pathlib import Path

from vedirect_influx.config import Config

PAGE = Path(__file__).parent.parent / "docs" / "reference" / "configuration.md"


def test_every_config_field_is_documented():
    """Each ``Config`` field appears as the second column of a table row, and no extra ones."""
    documented = set(re.findall(r"^\| `[a-z_.]+` \| `([a-z_]+)` \|", PAGE.read_text(), re.M))
    assert documented == {f.name for f in fields(Config)}
