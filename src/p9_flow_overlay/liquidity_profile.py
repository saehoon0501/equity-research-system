"""Liquidity / tradability profile + sizing haircut — WS-7.1 (Phase 3, OPTIONAL).

Computes a *tradability profile* for a candidate position from average-daily-
volume (ADV) inputs and maps it to a **sizing haircut multiplier** in (0, 1.0].
The multiplier feeds `src/sizing/composable.py::composable_size(
liquidity_multiplier=...)` (the `CalibratedWeights.liquidity` exponent already
exists, default 1.0 == no-op).

Direction of effect (acceptance contract):
    - liquid large-cap            => multiplier == 1.0 (NO haircut)
    - thin / illiquid small-cap   => multiplier  < 1.0 (monotone: thinner =>
                                     smaller multiplier)
    - never > 1.0 — liquidity can only *haircut* size, never *boost* it.

ADV math reuse (per WS-7.1 plan: "the ADV math already exists in the flow-
overlay's gex_aggregator — REUSE by import rather than re-derive"):
    The flow-overlay's `gex_aggregator.classify_gamma_regime` already consumes
    a `notional_adv_30d` quantity, documented there (gex_aggregator.py:292-293)
    as "trailing-30d average daily notional dollar volume (avg shares × avg
    adj_close)" — the SpotGamma / Vásquez et al. (Jan 2025, Cboe) GEX/ADV
    normalization convention. We REUSE that exact notional-ADV definition here
    via `compute_notional_adv_30d`, and we import `CONTRACT_MULTIPLIER` from
    gex_aggregator so the contract-size convention stays single-sourced (used
    when sizing options-leg notional alongside equity notional). The liquidity
    haircut is the *consumer-side* counterpart of the same ADV math the
    gamma-regime normalizer uses: `classify_gamma_regime(notional_adv_30d=...)`
    normalizes GEX by notional ADV; here we normalize *position notional* by
    the same notional ADV to get days-to-liquidate.

Injectable seam (offline-testable):
    Market data (ADV, spread, market cap) is supplied as a `LiquidityInputs`
    dataclass OR via an optional `fetcher` callable (ticker -> LiquidityInputs).
    The live ADV/spread fetch (from `src/market_data`) is the INTEGRATION
    BOUNDARY and is intentionally NOT wired here — `fetcher` defaults to None,
    so every code path in this module is pure + offline.

Threshold reasoning — days-to-liquidate (DTL) bands:
    Days-to-liquidate = position_notional / notional_adv_30d, optionally scaled
    by a participation cap (you can only trade ~`participation_cap` of ADV/day
    without moving the market). Institutional transaction-cost-analysis (TCA)
    practice (e.g. Kyle 1985 price-impact, Almgren-Chriss 2000 optimal
    execution, and common buy-side liquidity-risk limits) treats:
        DTL <= 1 day   : highly liquid — exit in a session — NO haircut.
        DTL 1–3 days   : liquid       — modest impact — mild haircut.
        DTL 3–10 days  : moderate     — multi-day unwind — material haircut.
        DTL > 10 days  : illiquid     — unwind risk dominates — heavy haircut.
    Bid/ask spread and market-cap tier act as additional independent haircuts
    (wide spread => transaction-cost drag; micro/nano-cap => structural
    fragility), combined multiplicatively and floored so the product stays in
    (0, 1.0].
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Optional, Sequence

# REUSE: import the contract-size convention from the flow-overlay GEX
# aggregator so options-leg notional is sized with the same multiplier the
# gamma-regime layer uses (single-sourced; see module docstring).
from src.p9_flow_overlay.gex_aggregator import CONTRACT_MULTIPLIER

__all__ = [
    "LiquidityInputs",
    "LiquidityProfile",
    "compute_notional_adv_30d",
    "liquidity_profile",
    "liquidity_haircut_multiplier",
    "DTL_BAND_LIQUID",
    "DTL_BAND_MODERATE",
    "DTL_BAND_ILLIQUID",
]

# --------------------------------------------------------------------------- #
# Tunable thresholds (documented in module docstring)                         #
# --------------------------------------------------------------------------- #

# Days-to-liquidate band edges (in trading days).
DTL_BAND_LIQUID = 1.0       # DTL <= 1 day  → no DTL haircut
DTL_BAND_MODERATE = 3.0     # 1 < DTL <= 3  → mild haircut
DTL_BAND_ILLIQUID = 10.0    # 3 < DTL <= 10 → material; > 10 → heavy

# Multiplier applied at each DTL band (the haircut FLOOR reached at/above the
# band's upper edge; we interpolate linearly inside a band so the haircut is
# monotone-continuous in DTL, satisfying "thinner => smaller").
_DTL_MULT_AT_LIQUID = 1.00      # DTL <= 1
_DTL_MULT_AT_MODERATE = 0.85    # DTL == 3
_DTL_MULT_AT_ILLIQUID = 0.50    # DTL == 10
_DTL_MULT_FLOOR = 0.20          # asymptotic floor for DTL >> 10

# Participation cap: fraction of ADV one can trade per day without undue
# impact. DTL is divided by this (you need 1/cap as many days). Default 20%
# is a common buy-side execution assumption.
DEFAULT_PARTICIPATION_CAP = 0.20

# Bid/ask spread (in basis points of mid) haircut bands. Tight spreads (large
# caps) cost ~1–5 bps round-trip; wide spreads (small/micro) 50+ bps.
_SPREAD_BPS_TIGHT = 10.0     # <= 10 bps → no spread haircut
_SPREAD_BPS_WIDE = 100.0     # >= 100 bps → full spread haircut
_SPREAD_MULT_FLOOR = 0.70    # heaviest spread-only haircut

# Market-cap tier haircut. Large/mega caps are structurally liquid; micro/nano
# caps carry fragility independent of today's ADV snapshot.
_MKT_CAP_LARGE = 10_000_000_000.0    # >= $10B → no cap haircut
_MKT_CAP_SMALL = 2_000_000_000.0     # >= $2B  → small-cap, mild
_MKT_CAP_MICRO = 300_000_000.0       # >= $300M → micro, material; below → nano
_MKT_CAP_MULT_LARGE = 1.00
_MKT_CAP_MULT_SMALL = 0.95
_MKT_CAP_MULT_MICRO = 0.80
_MKT_CAP_MULT_NANO = 0.60

# Absolute floor on the combined multiplier — keeps the result strictly in
# (0, 1.0]; the geometric product can never reach 0.
_COMBINED_FLOOR = 0.05


# --------------------------------------------------------------------------- #
# Injectable input seam                                                       #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class LiquidityInputs:
    """Market-data inputs for a tradability profile. INJECTABLE SEAM.

    Either pass `notional_adv_30d` directly, OR pass the raw
    `shares_volume_30d` + `adj_close_30d` series and let
    `compute_notional_adv_30d` derive it (the gex_aggregator ADV definition:
    avg shares × avg adj_close).

    All fields except `position_notional` are optional so partial data still
    yields a (more conservative-where-unknown) profile. Fields left None are
    simply skipped (no haircut from that dimension) — never assumed illiquid.
    """

    position_notional: float                         # $ size of the candidate position
    notional_adv_30d: Optional[float] = None         # $ avg daily notional volume
    shares_volume_30d: Optional[Sequence[float]] = None   # daily share volume series
    adj_close_30d: Optional[Sequence[float]] = None       # daily adj-close series
    bid_ask_spread_bps: Optional[float] = None       # round-trip spread in bps of mid
    market_cap: Optional[float] = None               # $ market capitalization
    participation_cap: float = DEFAULT_PARTICIPATION_CAP
    # Optional options-leg context (sized with CONTRACT_MULTIPLIER, the reused
    # gex_aggregator convention). When provided, adds the option's underlying-
    # equivalent notional to position_notional for the DTL calc.
    option_contracts: Optional[float] = None         # number of option contracts
    option_underlying_price: Optional[float] = None  # underlying price per share


@dataclass(frozen=True)
class LiquidityProfile:
    """Computed tradability profile. Pure function of LiquidityInputs."""

    effective_notional: float            # position notional incl. options leg
    notional_adv_30d: Optional[float]    # the ADV used (derived or supplied)
    days_to_liquidate: Optional[float]   # effective_notional / (adv × cap)
    bid_ask_spread_bps: Optional[float]
    market_cap: Optional[float]
    # Per-dimension haircut multipliers, all in (0, 1.0]; product (floored)
    # is the final haircut. Surfaced for audit/telemetry.
    dtl_multiplier: float
    spread_multiplier: float
    market_cap_multiplier: float
    # True when a *provided* numeric input (ADV/spread/market-cap) or a derived
    # value was non-finite (NaN/inf) — i.e. a genuine data gap. The affected
    # dimension(s) degrade to the benign 1.0-skip, so this flag is the ONLY way
    # a monitor can distinguish "garbage data → no haircut applied" from a
    # legitimately liquid large-cap that also scores 1.0. Cleanly-missing (None)
    # inputs do NOT raise this flag — missing-by-design is the documented skip,
    # whereas non-finite is corrupt data that must be observable. WS-7.1 fix.
    liquidity_data_unavailable: bool = False

    def to_payload(self) -> dict:
        return {
            "effective_notional": round(self.effective_notional, 2),
            "notional_adv_30d": (
                round(self.notional_adv_30d, 2)
                if self.notional_adv_30d is not None
                else None
            ),
            "days_to_liquidate": (
                round(self.days_to_liquidate, 4)
                if self.days_to_liquidate is not None
                else None
            ),
            "bid_ask_spread_bps": self.bid_ask_spread_bps,
            "market_cap": self.market_cap,
            "dtl_multiplier": round(self.dtl_multiplier, 4),
            "spread_multiplier": round(self.spread_multiplier, 4),
            "market_cap_multiplier": round(self.market_cap_multiplier, 4),
            "liquidity_data_unavailable": self.liquidity_data_unavailable,
        }


# --------------------------------------------------------------------------- #
# Non-finite (NaN/inf) normalization                                          #
# --------------------------------------------------------------------------- #


def _finite_or_none(value: Optional[float]) -> Optional[float]:
    """Normalize a numeric input to the documented "unavailable => skip" state.

    Returns the value unchanged when it is a real finite number; returns None
    for both genuinely-missing (None) AND non-finite garbage (NaN / ±inf).

    This is the single chokepoint that makes NaN handling CONSISTENT across all
    three haircut dimensions (DTL / spread / market-cap): a garbage reading is
    routed through the SAME None/skip path as a cleanly-missing input, instead
    of silently masquerading as a no-haircut 1.0 (DTL/spread) OR an arbitrary
    0.60 nano-cap haircut (market-cap). See module docstring + WS-7.1 bug fix.

    NOTE: collapsing NaN→None means the *multiplier* for that dimension is the
    benign 1.0-skip. That alone would still fail-open, so the profile separately
    raises a `liquidity_data_unavailable` flag whenever a provided numeric input
    was non-finite — so a monitor sees the data gap rather than a clean 1.0.
    """
    if value is None:
        return None
    if not math.isfinite(value):
        return None
    return value


# --------------------------------------------------------------------------- #
# ADV math (REUSED definition from gex_aggregator)                            #
# --------------------------------------------------------------------------- #


def compute_notional_adv_30d(
    shares_volume_30d: Sequence[float],
    adj_close_30d: Sequence[float],
) -> Optional[float]:
    """Trailing-30d average daily *notional* dollar volume.

    This is the SAME quantity `gex_aggregator.classify_gamma_regime`'s
    `notional_adv_30d` parameter expects, defined in gex_aggregator.py:292-293
    as "avg shares × avg adj_close" (SpotGamma / Vásquez 2025 GEX/ADV
    convention). Re-implemented here as a small importable helper because the
    aggregator computes it inline; the *definition* is reused, not re-derived.

    Returns None when either series is empty (insufficient data → caller skips
    the DTL dimension rather than assuming illiquid).
    """
    if not shares_volume_30d or not adj_close_30d:
        return None
    avg_shares = sum(shares_volume_30d) / len(shares_volume_30d)
    avg_close = sum(adj_close_30d) / len(adj_close_30d)
    notional = avg_shares * avg_close
    # A NaN/inf anywhere in the raw series propagates to a non-finite notional;
    # treat that as "unavailable" rather than letting a NaN ADV escape (which
    # would later yield a NaN DTL → silent no-haircut 1.0). See WS-7.1 fix.
    if not math.isfinite(notional) or notional <= 0:
        return None
    return notional


# --------------------------------------------------------------------------- #
# Per-dimension haircut helpers                                               #
# --------------------------------------------------------------------------- #


def _interp(x: float, x0: float, x1: float, y0: float, y1: float) -> float:
    """Linear interpolation of y over [x0, x1] for x in that range."""
    if x1 == x0:
        return y1
    t = (x - x0) / (x1 - x0)
    return y0 + t * (y1 - y0)


def _dtl_multiplier(days_to_liquidate: Optional[float]) -> float:
    """Map days-to-liquidate to a multiplier in (0, 1.0]. Monotone-decreasing:
    larger DTL (thinner liquidity relative to position) => smaller multiplier.

    Piecewise-linear across the documented bands; asymptotes to _DTL_MULT_FLOOR
    far beyond the illiquid edge.

    A non-finite DTL (NaN/inf — e.g. from a NaN ADV or 0/0) is normalized to the
    same "unavailable => skip" path as None, so the most-illiquid-possible NaN
    signal can NEVER masquerade as the no-haircut 1.0 of a liquid name. The
    benign 1.0 returned here is matched by the profile's
    `liquidity_data_unavailable` flag so the gap is observable. See WS-7.1 fix."""
    days_to_liquidate = _finite_or_none(days_to_liquidate)
    if days_to_liquidate is None:
        return 1.0  # unknown ADV → no DTL haircut (other dims may still bite)
    d = max(0.0, days_to_liquidate)
    if d <= DTL_BAND_LIQUID:
        return _DTL_MULT_AT_LIQUID
    if d <= DTL_BAND_MODERATE:
        return _interp(
            d, DTL_BAND_LIQUID, DTL_BAND_MODERATE,
            _DTL_MULT_AT_LIQUID, _DTL_MULT_AT_MODERATE,
        )
    if d <= DTL_BAND_ILLIQUID:
        return _interp(
            d, DTL_BAND_MODERATE, DTL_BAND_ILLIQUID,
            _DTL_MULT_AT_MODERATE, _DTL_MULT_AT_ILLIQUID,
        )
    # DTL > illiquid edge: decay from the illiquid multiplier toward the floor.
    # Reach ~floor by DTL == 2× the illiquid edge; clamp below.
    decayed = _interp(
        d, DTL_BAND_ILLIQUID, 2 * DTL_BAND_ILLIQUID,
        _DTL_MULT_AT_ILLIQUID, _DTL_MULT_FLOOR,
    )
    return max(_DTL_MULT_FLOOR, decayed)


def _spread_multiplier(bid_ask_spread_bps: Optional[float]) -> float:
    """Map bid/ask spread (bps) to a multiplier in [_SPREAD_MULT_FLOOR, 1.0].
    Wider spread => smaller multiplier (transaction-cost drag).

    A non-finite spread (NaN/inf) is normalized to the None/skip path for
    consistency with the other dimensions (WS-7.1 fix)."""
    bid_ask_spread_bps = _finite_or_none(bid_ask_spread_bps)
    if bid_ask_spread_bps is None:
        return 1.0
    s = max(0.0, bid_ask_spread_bps)
    if s <= _SPREAD_BPS_TIGHT:
        return 1.0
    if s >= _SPREAD_BPS_WIDE:
        return _SPREAD_MULT_FLOOR
    return _interp(s, _SPREAD_BPS_TIGHT, _SPREAD_BPS_WIDE, 1.0, _SPREAD_MULT_FLOOR)


def _market_cap_multiplier(market_cap: Optional[float]) -> float:
    """Step-function haircut by market-cap tier. Large/mega => 1.0.

    A non-finite market cap (NaN/inf) is normalized to the None/skip path
    (=> 1.0) rather than collapsing through the comparison chain to the NANO
    tier (0.60). This makes NaN handling CONSISTENT with the DTL/spread dims —
    previously a NaN cap was the lone dimension that haircut on garbage
    (bug 3). The gap is surfaced via the profile flag. See WS-7.1 fix."""
    market_cap = _finite_or_none(market_cap)
    if market_cap is None:
        return 1.0
    if market_cap >= _MKT_CAP_LARGE:
        return _MKT_CAP_MULT_LARGE
    if market_cap >= _MKT_CAP_SMALL:
        return _MKT_CAP_MULT_SMALL
    if market_cap >= _MKT_CAP_MICRO:
        return _MKT_CAP_MULT_MICRO
    return _MKT_CAP_MULT_NANO


# --------------------------------------------------------------------------- #
# Public API                                                                  #
# --------------------------------------------------------------------------- #


def liquidity_profile(
    inputs: Optional[LiquidityInputs] = None,
    *,
    ticker: Optional[str] = None,
    fetcher: Optional[Callable[[str], LiquidityInputs]] = None,
) -> LiquidityProfile:
    """Compute a tradability profile.

    Provide EITHER an explicit `inputs` (offline / fixture path) OR a
    `ticker` + `fetcher` callable (integration path — `fetcher` is the seam
    onto `src/market_data`; defaults to None and is NOT wired here).

    Args:
        inputs: explicit LiquidityInputs (offline-testable path).
        ticker: symbol to resolve via `fetcher`.
        fetcher: callable(ticker) -> LiquidityInputs. THE INTEGRATION SEAM.

    Returns:
        LiquidityProfile (pure function of the resolved inputs).
    """
    if inputs is None:
        if fetcher is None or ticker is None:
            raise ValueError(
                "liquidity_profile needs either `inputs`, or both `ticker` "
                "and a `fetcher` callable (the market-data seam)."
            )
        inputs = fetcher(ticker)

    # Track whether any *provided* numeric input (or a derived value) was
    # non-finite (NaN/inf) — a genuine data gap that must be surfaced, distinct
    # from a cleanly-missing (None) input. WS-7.1 fix (bugs 1–3).
    data_unavailable = False

    # Resolve notional ADV: explicit value wins; else derive from raw series
    # using the gex_aggregator ADV definition.
    adv = inputs.notional_adv_30d
    if adv is not None:
        # Bug 1 & 2: a NaN/inf ADV must NOT pass the `> 0` guard as if absent
        # and silently yield the no-haircut 1.0. Normalize to None (skip) AND
        # flag the gap so it is observable rather than masquerading as liquid.
        if not math.isfinite(adv):
            data_unavailable = True
            adv = None
    else:
        # Derive from raw series. A NaN/inf in the raw series propagates to a
        # non-finite notional; compute_notional_adv_30d returns None for that —
        # but we must distinguish "garbage series" (flag) from "empty/no series"
        # (clean skip). Only flag when raw data was actually supplied yet failed
        # the finiteness check.
        raw_supplied = bool(inputs.shares_volume_30d) and bool(inputs.adj_close_30d)
        adv = compute_notional_adv_30d(
            inputs.shares_volume_30d or [],
            inputs.adj_close_30d or [],
        )
        if raw_supplied and adv is None:
            non_finite_raw = any(
                not math.isfinite(v) for v in inputs.shares_volume_30d
            ) or any(not math.isfinite(v) for v in inputs.adj_close_30d)
            if non_finite_raw:
                data_unavailable = True

    # Effective notional: equity position + optional options-leg notional sized
    # with the reused CONTRACT_MULTIPLIER convention from gex_aggregator.
    effective_notional = inputs.position_notional
    if (
        inputs.option_contracts is not None
        and inputs.option_underlying_price is not None
    ):
        effective_notional += (
            inputs.option_contracts
            * CONTRACT_MULTIPLIER
            * inputs.option_underlying_price
        )

    # Days-to-liquidate = effective_notional / (ADV × participation_cap).
    days_to_liquidate: Optional[float] = None
    if adv is not None and adv > 0:
        cap = inputs.participation_cap if inputs.participation_cap > 0 else 1.0
        tradable_per_day = adv * cap
        days_to_liquidate = effective_notional / tradable_per_day
        # A non-finite effective_notional (NaN position / option inputs) yields a
        # non-finite DTL → the most-illiquid-possible signal. Bug 1: never let
        # that collapse into the liquid band's clean 1.0; flag and let
        # _dtl_multiplier normalize it to the benign skip.
        if not math.isfinite(days_to_liquidate):
            data_unavailable = True

    # Provided-but-non-finite spread / market-cap are also genuine data gaps.
    if inputs.bid_ask_spread_bps is not None and not math.isfinite(
        inputs.bid_ask_spread_bps
    ):
        data_unavailable = True
    if inputs.market_cap is not None and not math.isfinite(inputs.market_cap):
        data_unavailable = True

    return LiquidityProfile(
        effective_notional=effective_notional,
        notional_adv_30d=adv,
        days_to_liquidate=days_to_liquidate,
        bid_ask_spread_bps=inputs.bid_ask_spread_bps,
        market_cap=inputs.market_cap,
        dtl_multiplier=_dtl_multiplier(days_to_liquidate),
        spread_multiplier=_spread_multiplier(inputs.bid_ask_spread_bps),
        market_cap_multiplier=_market_cap_multiplier(inputs.market_cap),
        liquidity_data_unavailable=data_unavailable,
    )


def liquidity_haircut_multiplier(profile: LiquidityProfile) -> float:
    """Map a LiquidityProfile to a sizing haircut multiplier in (0, 1.0].

    Combines the three per-dimension multipliers multiplicatively (each is a
    risk overlay; any one saying "tighten" should compound, matching the
    composable-sizing geometric-product semantics). The result is floored at
    `_COMBINED_FLOOR` and capped at 1.0 — liquidity ONLY haircuts, never
    boosts.

    Acceptance:
        - liquid large-cap (DTL<=1, tight spread, mega-cap) => 1.0
        - thinner => strictly smaller (monotone via _dtl_multiplier)
        - always in (0, 1.0]
    """
    combined = (
        profile.dtl_multiplier
        * profile.spread_multiplier
        * profile.market_cap_multiplier
    )
    # Defense-in-depth: a non-finite product (should be impossible now that each
    # dimension normalizes NaN/inf, but never fail open on garbage) collapses to
    # the conservative floor rather than NaN/inf. WS-7.1 fix: the final
    # multiplier must ALWAYS be finite, in (0, 1.0].
    if not math.isfinite(combined):
        return _COMBINED_FLOOR
    # Clamp into (0, 1.0]: floor strictly above 0, cap at 1.0 (never boost).
    return min(1.0, max(_COMBINED_FLOOR, combined))
