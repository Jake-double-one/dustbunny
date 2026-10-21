"""Dustbunny - finds orphaned Docker appdata folders."""

import os

# Release builds set DUSTBUNNY_VERSION (e.g. "0.1.0" or "0.1.0-3-g1a2b3c4").
__version__ = os.environ.get("DUSTBUNNY_VERSION", "").removeprefix("v") or "0.3.0"
