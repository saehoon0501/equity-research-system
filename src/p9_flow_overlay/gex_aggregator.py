"""Gamma-regime sub-signal compute layer — v0.2.

Aggregates dealer Gamma Exposure (GEX) from a Polygon options chain, buckets
by DTE, re-prices via Black-Scholes across a spot grid to find the zero-gamma
level, and classifies the regime into {positive, neutral, negative}.

Architectural decoupling: pure compute on already-fetched inputs. The
flow-overlay agent fetches the chain via `mcp__polygon__get_options_chain`
and passes the contract list into this module.

Polygon return shape (per src/mcp/polygon/server.py:163-196):
    contracts: list[dict] where each dict has:
        strike: float
        expiry: str  (ISO-8601 YYYY-MM-DD)
        type: "call" | "put"
        open_interest: int | None
        volume: int | None
        iv: float | None
        delta: float | None
        gamma: float | None  ← KEY field for v0.2; None for illiquid contracts
        theta: float | None
        vega: float | None

CRITICAL: gamma and open_interest may be None for illiquid contracts. The
aggregator treats None as 0 contribution (no signal from that strike).

Dealer-sign convention (configurable per parameters_active):
    spotgamma (v0.2 default): dealers long calls (+1), short puts (-1)
    squeezemetrics (alternative): dealers buy calls / sell puts (calls -1, puts +1)

Per-strike GEX formula (SqueezeMetrics canonical):
    GEX = gamma × open_interest × contract_size × spot² × 0.01 × dealer_sign

Spec references:
- plans/first-let-s-plan-the-serialized-hanrahan.md (v0.2 plan, 2026-05-23)
- Amaya/García-Arés/Pearson/Vásquez (Jan 2025, Cboe) — primary measurement
- SqueezeMetrics DIX/GEX white paper (2017) — formula provenance
"""
from __future__ import annotations

import math
from datetime import date
from typing import Optional

# Note: scipy is available as a transitive dep but not needed here. BS gamma
# is N'(d1) / (S·σ·√T) — the normal PDF, computed inline via math.exp.
# The normal CDF (scipy.special.ndtr) is only needed for BS delta/price.

# Module-top constants
CONTRACT_MULTIPLIER = 100  # standard US equity options
DEFAULT_DTE_BOUNDARIES = (0, 7, 30, 90)
DEFAULT_GRID_PCT = 0.10
DEFAULT_GRID_STEPS = 20


def compute_per_strike_gex(
    contract: dict,
    spot: float,
    dealer_sign_calls: int = 1,
    dealer_sign_puts: int = -1,
) -> float:
    """Per-strike dealer Gamma Exposure in dollars.

    Formula: gamma × OI × contract_size × spot² × 0.01 × dealer_sign

    Args:
        contract: dict from Polygon options chain (must have 'gamma',
            'open_interest', 'type' keys).
        spot: current underlying price.
        dealer_sign_calls: +1 if dealers long calls (SpotGamma) else -1.
        dealer_sign_puts: -1 if dealers short puts (SpotGamma) else +1.

    Returns:
        Dollar GEX contribution from this strike. 0.0 when gamma or
        open_interest is None (illiquid contract — no signal).
    """
    gamma = contract.get("gamma")
    oi = contract.get("open_interest")
    if gamma is None or oi is None:
        return 0.0
    contract_type = contract.get("type")
    if contract_type == "call":
        sign = dealer_sign_calls
    elif contract_type == "put":
        sign = dealer_sign_puts
    else:
        return 0.0  # unknown type — defensive
    return gamma * oi * CONTRACT_MULTIPLIER * spot * spot * 0.01 * sign


def _dte_from_expiry(expiry_str: str, as_of: date) -> int:
    """Return integer days-to-expiry. Negative values clamped to 0."""
    expiry = date.fromisoformat(expiry_str)
    return max(0, (expiry - as_of).days)


def _bucket_label(dte: int, boundaries: tuple[int, ...]) -> str:
    """Map a DTE value to its bucket label per the boundaries tuple."""
    if dte <= 0:
        return "0DTE"
    sorted_b = sorted(boundaries)
    for i, b in enumerate(sorted_b[1:], start=1):
        if dte <= b:
            return f"{sorted_b[i - 1] + 1}-{b}d"
    return f"{sorted_b[-1] + 1}d+"


def aggregate_gex_by_dte_bucket(
    contracts: list[dict],
    spot: float,
    as_of: date,
    dealer_sign_calls: int = 1,
    dealer_sign_puts: int = -1,
    dte_boundaries: tuple[int, ...] = DEFAULT_DTE_BOUNDARIES,
) -> dict[str, float]:
    """Aggregate per-strike GEX into DTE buckets + total.

    Args:
        contracts: list of Polygon contract dicts.
        spot: current underlying price.
        as_of: reference date for DTE calculation.
        dealer_sign_calls / dealer_sign_puts: per dealer-sign convention.
        dte_boundaries: bucket boundaries (default (0, 7, 30, 90)).

    Returns:
        dict with bucket labels mapped to summed dollar GEX, plus
        'total_net_gex' key for the sum across all buckets.
    """
    buckets: dict[str, float] = {}
    total = 0.0
    for contract in contracts:
        expiry = contract.get("expiry")
        if not expiry:
            continue
        try:
            dte = _dte_from_expiry(expiry, as_of)
        except (ValueError, TypeError):
            continue
        label = _bucket_label(dte, dte_boundaries)
        gex = compute_per_strike_gex(
            contract, spot, dealer_sign_calls, dealer_sign_puts
        )
        buckets[label] = buckets.get(label, 0.0) + gex
        total += gex
    buckets["total_net_gex"] = total
    return buckets


def _bs_gamma_at_spot(
    spot: float,
    strike: float,
    ttm_years: float,
    iv: float,
    rf: float = 0.0,
) -> float:
    """Closed-form Black-Scholes gamma.

    gamma = N'(d1) / (S × σ × √T)
        where d1 = (ln(S/K) + (r + σ²/2)·T) / (σ√T)
        and N'(x) = exp(-x²/2) / √(2π)

    Args:
        spot: current underlying price.
        strike: option strike price.
        ttm_years: time-to-expiry in years (e.g., 30/365 for 30-day option).
        iv: implied volatility (annualized, decimal — e.g., 0.30 for 30%).
        rf: continuously-compounded risk-free rate (decimal, default 0).

    Returns:
        Gamma per 1-share contract. Returns 0.0 for degenerate inputs
        (ttm <= 0, iv <= 0, spot <= 0, strike <= 0).
    """
    if spot <= 0 or strike <= 0 or ttm_years <= 0 or iv <= 0:
        return 0.0
    sigma_sqrt_t = iv * math.sqrt(ttm_years)
    d1 = (math.log(spot / strike) + (rf + 0.5 * iv * iv) * ttm_years) / sigma_sqrt_t
    n_prime_d1 = math.exp(-0.5 * d1 * d1) / math.sqrt(2.0 * math.pi)
    return n_prime_d1 / (spot * sigma_sqrt_t)


def compute_zero_gamma_level(
    contracts: list[dict],
    spot: float,
    as_of: date,
    rf: float = 0.0,
    dealer_sign_calls: int = 1,
    dealer_sign_puts: int = -1,
    grid_pct: float = DEFAULT_GRID_PCT,
    grid_steps: int = DEFAULT_GRID_STEPS,
) -> Optional[float]:
    """Find the spot at which aggregate net GEX crosses zero.

    Re-prices gamma at each spot in [spot × (1 - grid_pct), spot × (1 + grid_pct)]
    linearly across grid_steps points. Returns the linearly-interpolated spot
    where aggregate net GEX crosses zero.

    Args:
        contracts: list of Polygon contract dicts (must contain iv, strike, expiry, type, open_interest).
        spot: current underlying price.
        as_of: reference date for DTE/TTM calculation.
        rf: risk-free rate for BS re-pricing.
        dealer_sign_calls / dealer_sign_puts: dealer-sign convention.
        grid_pct: spot grid half-range (e.g., 0.10 = ±10%).
        grid_steps: number of grid points.

    Returns:
        Zero-gamma spot level (float) if found within the grid;
        None if no crossing detected or insufficient IV data to re-price.
    """
    if grid_steps < 2:
        return None
    # Filter contracts that have the inputs needed for BS re-pricing
    usable = [
        c for c in contracts
        if c.get("iv") is not None
        and c.get("iv", 0) > 0
        and c.get("strike") is not None
        and c.get("strike", 0) > 0
        and c.get("expiry") is not None
        and c.get("open_interest") is not None
        and c.get("type") in ("call", "put")
    ]
    if not usable:
        return None

    lo = spot * (1.0 - grid_pct)
    hi = spot * (1.0 + grid_pct)
    step = (hi - lo) / (grid_steps - 1)

    def net_gex_at(s: float) -> float:
        """Aggregate dollar GEX across all usable contracts at hypothetical spot s."""
        total = 0.0
        for c in usable:
            try:
                ttm = _dte_from_expiry(c["expiry"], as_of) / 365.0
            except (ValueError, TypeError):
                continue
            gamma_at_s = _bs_gamma_at_spot(
                spot=s,
                strike=float(c["strike"]),
                ttm_years=ttm,
                iv=float(c["iv"]),
                rf=rf,
            )
            sign = dealer_sign_calls if c["type"] == "call" else dealer_sign_puts
            total += gamma_at_s * int(c["open_interest"]) * CONTRACT_MULTIPLIER * s * s * 0.01 * sign
        return total

    grid = [(lo + i * step, net_gex_at(lo + i * step)) for i in range(grid_steps)]
    # Find adjacent pair where sign flips
    for i in range(len(grid) - 1):
        s1, g1 = grid[i]
        s2, g2 = grid[i + 1]
        if g1 == 0:
            return s1
        if g2 == 0:
            return s2
        if (g1 > 0) != (g2 > 0):
            # linear interpolation between (s1, g1) and (s2, g2) to find s where g=0
            return s1 + (s2 - s1) * (-g1) / (g2 - g1)
    return None  # no crossing in range


def classify_gamma_regime(
    contracts: list[dict],
    spot: float,
    as_of: date,
    positive_threshold_normalized: float,
    negative_threshold_normalized: float,
    dealer_sign_convention: str = "spotgamma",
    regime_flip_signal_method: str = "zero_gamma_inflection",
    dte_boundaries: tuple[int, ...] = DEFAULT_DTE_BOUNDARIES,
    rf: float = 0.0,
    grid_pct: float = DEFAULT_GRID_PCT,
    grid_steps: int = DEFAULT_GRID_STEPS,
    notional_adv_30d: Optional[float] = None,
    winsorize_at: Optional[float] = None,
) -> dict:
    """End-to-end gamma-regime classification.

    Args:
        contracts: list of Polygon contract dicts.
        spot: current underlying price.
        as_of: reference date for DTE/TTM.
        positive_threshold_normalized: normalized net-GEX above which bin=positive.
        negative_threshold_normalized: normalized net-GEX below which bin=negative.
        dealer_sign_convention: "spotgamma" | "squeezemetrics".
        regime_flip_signal_method: "zero_gamma_inflection" | "volatility_trigger" (volatility_trigger unimplemented in v0.2).
        dte_boundaries: bucket boundaries.
        rf: risk-free rate for BS re-pricing.
        grid_pct / grid_steps: zero-gamma search params.
        notional_adv_30d: trailing-30d average daily notional dollar volume
            (avg shares × avg adj_close). When provided, normalization uses
            `net_gex / notional_adv_30d` (Vasquez 2025 + SpotGamma GEX/ADV
            convention). When None, back-compat falls back to the legacy
            formula `net_gex / (spot² × 100)`.
        winsorize_at: absolute-value bound applied to normalized_gex for BIN
            CLASSIFICATION ONLY; raw value retained in output. Prevents
            single-name dispersion from one-tail-dominating threshold
            calibration. When None, no winsorization (back-compat).

    Returns:
        {
            "bin": "positive" | "neutral" | "negative",
            "net_gex_at_spot": float (dollar GEX per 1% move),
            "normalized_gex": float (raw — see normalized_gex_unbounded note),
            "normalized_gex_unbounded": float (raw; equal to normalized_gex
                when no winsorization fired; differs only when raw exceeded
                ±winsorize_at — surfaces true squeeze episodes for telemetry),
            "winsorization_fired": bool (True iff abs(raw) > winsorize_at),
            "normalization_formula": "adv_30d" | "spot_squared" (audit lineage
                for which formula classify produced this result),
            "zero_gamma_distance_pct": float | None,
            "dte_bucket_decomp": dict[str, float],
            "dealer_sign_convention": str,
            "regime_flip_signal_method": str,
        }
    """
    if dealer_sign_convention == "spotgamma":
        sign_calls, sign_puts = 1, -1
    elif dealer_sign_convention == "squeezemetrics":
        sign_calls, sign_puts = -1, 1
    else:
        raise ValueError(
            f"unknown dealer_sign_convention {dealer_sign_convention!r}; "
            "must be 'spotgamma' or 'squeezemetrics'"
        )

    decomp = aggregate_gex_by_dte_bucket(
        contracts, spot, as_of,
        dealer_sign_calls=sign_calls,
        dealer_sign_puts=sign_puts,
        dte_boundaries=dte_boundaries,
    )
    net_gex = decomp.get("total_net_gex", 0.0)

    # Normalization formula: use notional_adv_30d when provided
    # (Vasquez 2025 + SpotGamma GEX/ADV convention); fall back to spot²×100
    # for back-compat when adv is None or non-positive.
    if notional_adv_30d is not None and notional_adv_30d > 0:
        normalized_raw = net_gex / notional_adv_30d
        formula = "adv_30d"
    else:
        normalizer = spot * spot * CONTRACT_MULTIPLIER
        normalized_raw = net_gex / normalizer if normalizer > 0 else 0.0
        formula = "spot_squared"

    # Winsorize for BIN CLASSIFICATION only; raw retained in output for
    # telemetry-alerting on true squeeze episodes (raw > winsorize_at).
    winsorization_fired = False
    if winsorize_at is not None and winsorize_at > 0:
        if normalized_raw > winsorize_at:
            normalized_for_bin = winsorize_at
            winsorization_fired = True
        elif normalized_raw < -winsorize_at:
            normalized_for_bin = -winsorize_at
            winsorization_fired = True
        else:
            normalized_for_bin = normalized_raw
    else:
        normalized_for_bin = normalized_raw

    if normalized_for_bin >= positive_threshold_normalized:
        bin_ = "positive"
    elif normalized_for_bin <= negative_threshold_normalized:
        bin_ = "negative"
    else:
        bin_ = "neutral"

    # Zero-gamma distance (only meaningful for zero_gamma_inflection method)
    zero_gamma_distance_pct: Optional[float] = None
    if regime_flip_signal_method == "zero_gamma_inflection":
        zg_level = compute_zero_gamma_level(
            contracts, spot, as_of,
            rf=rf,
            dealer_sign_calls=sign_calls,
            dealer_sign_puts=sign_puts,
            grid_pct=grid_pct,
            grid_steps=grid_steps,
        )
        if zg_level is not None:
            zero_gamma_distance_pct = (zg_level - spot) / spot

    # winsorization_fired is derivable (normalized_for_bin != normalized_raw)
    # but emitted explicitly because the flow-overlay agent's telemetry-alert
    # contract reads it as a boolean gate; the explicit field removes a
    # float-equality check from the consumer's reasoning path.
    return {
        "bin": bin_,
        "net_gex_at_spot": net_gex,
        "normalized_gex": normalized_for_bin,
        "normalized_gex_unbounded": normalized_raw,
        "winsorization_fired": winsorization_fired,
        "normalization_formula": formula,
        "zero_gamma_distance_pct": zero_gamma_distance_pct,
        "dte_bucket_decomp": {k: v for k, v in decomp.items() if k != "total_net_gex"},
        "dealer_sign_convention": dealer_sign_convention,
        "regime_flip_signal_method": regime_flip_signal_method,
    }


__all__ = [
    "CONTRACT_MULTIPLIER",
    "DEFAULT_DTE_BOUNDARIES",
    "DEFAULT_GRID_PCT",
    "DEFAULT_GRID_STEPS",
    "aggregate_gex_by_dte_bucket",
    "classify_gamma_regime",
    "compute_per_strike_gex",
    "compute_zero_gamma_level",
]
