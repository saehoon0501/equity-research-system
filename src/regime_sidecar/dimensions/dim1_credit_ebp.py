"""Dimension 1 — Excess Bond Premium (EBP).

Per v3 spec §3.3 row 1 + §4.1 ("single highest-edge: EBP, Gilchrist-Zakrajšek
2012"). The Fed publishes an updated EBP series monthly as a CSV at
federalreserve.gov.

Canonical URL: https://www.federalreserve.gov/econresdata/notes/feds-notes/2016/files/ebp_csv.csv

Fallback URLs (probed in order on primary failure): a few alternate paths
the Fed has used historically. On total network failure, we fall back to a
local cache at `cache/ebp_YYYYMMDD.csv` (most recent file) and tag the
result with `validation_depth = "STALE_CACHE"` so downstream consumers can
surface the fallback in `execution_context.risk_flags`.

Columns include `gz_spread`, `ebp` (excess bond premium), `est_prob`. The EBP
series itself is what we need.

State classification (v3 §4.1):
    benign    → ebp < 0
    stressed  → 0 ≤ ebp < 1
    crisis    → ebp ≥ 1

Cutoffs are GZ-2012 informed; tunable via `parameters` table (parameter_key:
`regime.dim1_credit_ebp.thresholds`).

Probability assignment: at v0.1 we deterministically pin probability=1.0 to
the headline state and 0.0 to the others (point classification with
single-bin probability). This satisfies the v3 spec's "probability
distribution per state" contract while deferring soft assignments to v0.5+
when MSGARCH-style smoothing comes online.
"""

from __future__ import annotations

import io
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import pandas as pd

from src.regime_sidecar.bocpd import latest_signals
from src.regime_sidecar.types import DimensionResult


logger = logging.getLogger(__name__)

# Fed EBP CSV — canonical + fallback URLs. The historical series is updated
# periodically; the canonical location below has been stable since the
# original 2016 FEDS-Note release. Fallbacks cover historical alternate
# paths the Fed has used.
_EBP_CSV_URLS: tuple[str, ...] = (
    "https://www.federalreserve.gov/econresdata/notes/feds-notes/2016/files/ebp_csv.csv",
    "https://www.federalreserve.gov/econres/notes/feds-notes/files/ebp_csv.csv",
)
_HTTP_TIMEOUT = 30.0

# Local cache directory for daily EBP snapshots. Lives under repo-root/cache.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_CACHE_DIR = _REPO_ROOT / "cache"

# State thresholds — see module docstring.
THRESHOLD_BENIGN_TO_STRESSED = 0.0
THRESHOLD_STRESSED_TO_CRISIS = 1.0


def _classify(ebp: float) -> str:
    if ebp < THRESHOLD_BENIGN_TO_STRESSED:
        return "benign"
    if ebp < THRESHOLD_STRESSED_TO_CRISIS:
        return "stressed"
    return "crisis"


def _cache_path_today() -> Path:
    return _CACHE_DIR / f"ebp_{date.today().strftime('%Y%m%d')}.csv"


def _most_recent_cache_file() -> Path | None:
    """Return the most-recent ebp_*.csv in the cache directory, or None."""
    if not _CACHE_DIR.exists():
        return None
    files = sorted(_CACHE_DIR.glob("ebp_*.csv"))
    return files[-1] if files else None


def _parse_ebp_csv(text: str) -> pd.DataFrame:
    df = pd.read_csv(io.StringIO(text))
    if "date" not in df.columns:
        raise RuntimeError(f"Unexpected EBP CSV schema: {df.columns.tolist()}")
    df["date"] = pd.to_datetime(df["date"]) + pd.offsets.MonthEnd(0)
    if "ebp" not in df.columns:
        raise RuntimeError(f"EBP CSV missing 'ebp' column: {df.columns.tolist()}")
    df = df.sort_values("date").reset_index(drop=True)
    return df


def _fetch_ebp_series() -> tuple[pd.DataFrame, str]:
    """Pull the EBP CSV from the canonical URL with fallbacks + caching.

    Returns:
        (df, source_tag) — source_tag is one of:
            "live:<url>"  — fresh fetch succeeded
            "cache:<path>" — fell back to local cache (stale)
    """
    last_exc: Exception | None = None
    for url in _EBP_CSV_URLS:
        try:
            with httpx.Client(timeout=_HTTP_TIMEOUT) as client:
                resp = client.get(url, follow_redirects=True)
                resp.raise_for_status()
            df = _parse_ebp_csv(resp.text)
            # Persist daily snapshot to local cache.
            try:
                _CACHE_DIR.mkdir(parents=True, exist_ok=True)
                _cache_path_today().write_text(resp.text)
            except Exception as cache_exc:  # noqa: BLE001
                logger.warning("ebp cache write failed: %s", cache_exc)
            return df, f"live:{url}"
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            logger.warning("ebp fetch failed for %s: %s", url, exc)

    # All live URLs failed — try local cache.
    cache_file = _most_recent_cache_file()
    if cache_file is not None:
        logger.warning("ebp falling back to stale cache: %s", cache_file)
        df = _parse_ebp_csv(cache_file.read_text())
        return df, f"cache:{cache_file.name}"

    raise RuntimeError(
        f"EBP fetch failed across all URLs and no local cache available. "
        f"Last error: {last_exc!r}"
    )


def compute(asof_date: date, history_days: int = 365) -> DimensionResult:
    """Compute Dim 1 (Excess Bond Premium) for `asof_date`.

    Args:
        asof_date: classification date.
        history_days: window of history for BOCPD; default ~12 months
            (cold-start seed in v3 §7.5).

    Returns:
        DimensionResult per `regime_classification_history` schema.

    Validation-depth handling:
        - "HIGH (Gilchrist-Zakrajšek 2012; AER)" on a successful live fetch.
        - "STALE_CACHE" if all live URLs failed and we fell back to a local
          cache file. Surface this in execution_context.risk_flags.
    """
    df, source_tag = _fetch_ebp_series()

    warnings: list[str] = []
    is_stale_cache = source_tag.startswith("cache:")
    if is_stale_cache:
        warnings.append(f"ebp_stale_cache:{source_tag.split(':', 1)[1]}")

    # Filter to <= asof_date and to last `history_days` of observations.
    cutoff_low = pd.Timestamp(asof_date) - pd.Timedelta(days=history_days)
    df = df[(df["date"] <= pd.Timestamp(asof_date)) & (df["date"] >= cutoff_low)]
    df = df.dropna(subset=["ebp"])

    if df.empty:
        warnings.append("ebp_series_empty_for_window")
        latest_ebp = float("nan")
        change_prob = 0.0
        short_run_mass = 0.0
        history_len = 0
    else:
        latest_ebp = float(df["ebp"].iloc[-1])
        history_len = int(len(df))
        change_prob, short_run_mass = latest_signals(df["ebp"].to_numpy())

    headline = _classify(latest_ebp) if not np.isnan(latest_ebp) else "benign"
    state_probs = {"benign": 0.0, "stressed": 0.0, "crisis": 0.0}
    state_probs[headline] = 1.0

    validation_depth = (
        "STALE_CACHE" if is_stale_cache
        else "HIGH (Gilchrist-Zakrajšek 2012; AER)"
    )

    return DimensionResult(
        dimension_id=1,
        dimension_name="credit_ebp",
        classification_date=asof_date,
        state_probabilities=state_probs,
        headline_state=headline,
        bocpd_change_probability=float(change_prob),
        bocpd_short_run_mass=float(short_run_mass),
        raw_inputs={
            "ebp_value": None if np.isnan(latest_ebp) else latest_ebp,
            "ebp_observation_date": (
                df["date"].iloc[-1].strftime("%Y-%m-%d") if not df.empty else None
            ),
            "thresholds": {
                "benign_to_stressed": THRESHOLD_BENIGN_TO_STRESSED,
                "stressed_to_crisis": THRESHOLD_STRESSED_TO_CRISIS,
            },
            "source_tag": source_tag,
            "source_urls_probed": list(_EBP_CSV_URLS),
            # Per v3 §4.1 method overlay #3: surprises (actual − consensus)
            # for credit-related macro inputs (e.g., bank Senior Loan Officer
            # Survey, IG/HY issuance flows) are not yet wired into this
            # dimension. EBP itself already encodes much of the credit-stress
            # signal, so the overlay's incremental edge here is small.
            "surprise_overlay_status": "deferred_to_v0.5",
        },
        history_length_days=history_len,
        validation_depth=validation_depth,
        warnings=warnings,
    )
