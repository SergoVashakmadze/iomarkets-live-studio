"""What the studio spends on Meta's Model API, and a daily cap on it.

Judges open the live product with our credit, and a full interview costs about $1.30 (SAM is
most of it). So every Meta call is metered from what the API reports (tokens, cached tokens,
web searches, SAM frames, seconds of audio streamed), priced at the Standard-mode rates
published at dev.meta.ai/docs/pricing-rate-limits (read 2026-10-27), and added to a ledger.
Once today's total (UTC) reaches `STUDIO_DAILY_BUDGET_USD` (default $10), new briefs and
interviews are refused; one already running finishes.
The deployed studio sets it in the Modal secret: $20 from 2026-10-31, for the testers' day.

The anchor's lip-sync on Modal's GPU is metered too ("gpu": render time at the L40S rate, plus
the five idle minutes after each interview), under the same daily total and its own smaller cap
(`STUDIO_GPU_DAILY_BUDGET_USD`, default $5): past it, the anchor is shown still until midnight UTC,
and page loads stop waking the GPU. The workstation's own GPU costs nothing and is not metered.
Muse Spark Open on Fireworks is billed by Fireworks, and is cents.
The ledger is a small JSON file (`STUDIO_LEDGER`, default under the user cache directory) so
it survives restarts. The Meta console's spend limit stays the backstop.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# US dollars, Standard mode.
SPARK_INPUT_PER_M = 1.25
SPARK_CACHED_PER_M = 0.15
SPARK_OUTPUT_PER_M = 4.25
WEB_SEARCH_EACH = 2.50 / 1000
ASR_PER_HOUR = 0.18
SAM_PER_FRAME = 0.20 / 1000
SAM_MIN_FRAMES = 50

DEFAULT_BUDGET_USD = 10.0
# Modal L40S $1.95/hour (modal.com/pricing, read 2026-10-30) plus 8 cores and 16 GiB (~$0.50).
GPU_PER_HOUR = 2.50
GPU_IDLE_S = 5 * 60  # the GPU's scaledown window after the last render (deploy/modal_app.py)
DEFAULT_GPU_BUDGET_USD = 5.0


class BudgetExceeded(RuntimeError):
    pass


def response_cost(body: dict[str, Any]) -> float:
    """The cost of one Responses result (Spark or SAM) from its own usage report."""
    usage = body.get("usage") or {}
    frames = usage.get("video_frames_processed")
    if frames:
        return max(int(frames), SAM_MIN_FRAMES) * SAM_PER_FRAME
    inp = int(usage.get("input_tokens") or 0)
    cached = int((usage.get("input_tokens_details") or {}).get("cached_tokens") or 0)
    out = int(usage.get("output_tokens") or 0)
    searches = sum(1 for item in body.get("output") or [] if item.get("type") == "web_search_call")
    return (
        (inp - cached) * SPARK_INPUT_PER_M / 1e6
        + cached * SPARK_CACHED_PER_M / 1e6
        + out * SPARK_OUTPUT_PER_M / 1e6
        + searches * WEB_SEARCH_EACH
    )


def asr_cost(seconds: float) -> float:
    return seconds / 3600 * ASR_PER_HOUR


class Ledger:
    def __init__(
        self,
        path: str | Path,
        budget_usd: float = DEFAULT_BUDGET_USD,
        gpu_budget_usd: float = DEFAULT_GPU_BUDGET_USD,
    ):
        self.path = Path(path)
        self.budget_usd = budget_usd
        self.gpu_budget_usd = gpu_budget_usd
        self._lock = threading.Lock()

    @classmethod
    def from_env(cls) -> Ledger:
        default = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
        path = os.environ.get("STUDIO_LEDGER") or default / "iomarkets-studio" / "ledger.json"
        budget = float(os.environ.get("STUDIO_DAILY_BUDGET_USD") or DEFAULT_BUDGET_USD)
        gpu = float(os.environ.get("STUDIO_GPU_DAILY_BUDGET_USD") or DEFAULT_GPU_BUDGET_USD)
        return cls(path, budget, gpu)

    def _read(self) -> dict[str, dict[str, float]]:
        try:
            return json.loads(self.path.read_text())
        except (FileNotFoundError, ValueError):
            return {}

    def charge(self, kind: str, usd: float) -> None:
        if usd <= 0:
            return
        day = _today()
        with self._lock:
            data = self._read()
            spent = data.setdefault(day, {})
            spent[kind] = round(spent.get(kind, 0.0) + usd, 6)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=1, sort_keys=True))
            tmp.replace(self.path)

    def today(self) -> dict[str, float]:
        return self._read().get(_today(), {})

    def spent_today(self) -> float:
        return round(sum(self.today().values()), 4)

    def gpu_allowed(self) -> bool:
        """Whether today's GPU cap, and the whole day's budget, leave room for lip-sync."""
        today = self.today()
        return today.get("gpu", 0.0) < self.gpu_budget_usd and sum(today.values()) < self.budget_usd

    def check(self) -> None:
        """Raise if today's budget is used up. Call before starting anything new."""
        spent = self.spent_today()
        if spent >= self.budget_usd:
            raise BudgetExceeded(
                f"Today's demo budget (${self.budget_usd:.2f}) is used up (${spent:.2f}). "
                "It resets at midnight UTC."
            )


def _today() -> str:
    return datetime.now(UTC).date().isoformat()


# The ledger Meta calls are charged to; set by the app (None: not metered).
current: Ledger | None = None


def charge(kind: str, usd: float) -> None:
    if current is not None:
        current.charge(kind, usd)


def gpu_seconds(seconds: float) -> float:
    return seconds * GPU_PER_HOUR / 3600


def gpu_allowed() -> bool:
    return current is None or current.gpu_allowed()
