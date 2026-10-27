"""Muse Spark Open, Meta's open-weights model, served by Fireworks.

Fireworks speaks the same Responses API, so the same client works with another base URL and
key. Measured 2026-10-27: a cold first call took 21 s, warm calls about 3 s. Built-in
`web_search` is accepted there but never runs (no search calls, no sources), so anything that
needs the web stays on Meta's Model API.

Licence (Muse Model License, 2026-10-15): "Built with Muse Spark Open" must be shown in the UI
or docs; it is in the page footer and the README.
"""

from __future__ import annotations

import os

from studio.meta.responses import ResponsesClient

FIREWORKS_BASE_URL = "https://api.fireworks.ai/inference/v1"
MUSE_SPARK_OPEN = "accounts/fireworks/models/muse-spark-open"
ATTRIBUTION = "Built with Muse Spark Open"


def open_weights_client() -> ResponsesClient | None:
    """A client for Muse Spark Open, or None when FIREWORKS_API_KEY is not set."""
    key = os.environ.get("FIREWORKS_API_KEY")
    if not key:
        return None
    return ResponsesClient(
        api_key=key, base_url=FIREWORKS_BASE_URL, model=MUSE_SPARK_OPEN, timeout=180
    )
