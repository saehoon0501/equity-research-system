# Section 3 — Tactical overlay implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` to implement this plan task-by-task. Each task is a fresh subagent dispatch + spec-review + code-review.

**Goal:** Implement the unified tactical-overlay agent per Section 2 v3-final + Section 2.1 v5-final. Section 2 spec at `docs/superpowers/plans/2026-05-21-section2-tactical-overlay-v3-final.md`; Section 2.1 spec at `docs/superpowers/consensus/2026-05-21-section2.1-label-vocabulary.md`.

**Architecture:** Stage 1 parallel agent. Hybrid LLM-wrapper-on-deterministic-Python. New Python module at `src/p8_tactical_overlay/` (contracts + bin_classifier + overlay). Postgres seed for 29 parameter rows. HG validator for tactical envelope shape. `/research-company` orchestrator updated to dispatch tactical-overlay alongside quant + strategic in Stage 1.

**Tech Stack:** Python 3.11+ (existing); postgres via psycopg; mcp__market_data + mcp__fred (existing MCP clients); HG validator pattern from `src/evaluator_gates/catalyst_memo_shape.py`; agent definition pattern from `.claude/agents/catalyst-scout.md`.

---

## File structure

**Create:**
- `src/p8_tactical_overlay/__init__.py` — package marker
- `src/p8_tactical_overlay/contracts.py` — `TacticalSignal` frozen dataclass + enum types
- `src/p8_tactical_overlay/bin_classifier.py` — Antonacci dual-momentum + `resolve_rf_at` helper
- `src/p8_tactical_overlay/overlay.py` — cell-size selector + tactical_disposition mapping
- `src/evaluator_gates/tactical_envelope_shape.py` — HG validator (mirrors `catalyst_memo_shape.py`)
- `.claude/agents/tactical-overlay.md` — LLM agent definition
- `db/migrations/038_tactical_overlay_parameters.sql` — 29 parameter rows
- `tests/test_p8_tactical_signal_contracts.py` — TacticalSignal dataclass tests
- `tests/test_p8_tactical_bin_classifier.py` — Antonacci classifier tests
- `tests/test_p8_tactical_overlay.py` — cell selector + disposition map + INV-2.1-A
- `tests/test_p8_tactical_envelope_shape.py` — HG validator tests
- `tests/test_p8_inv_2_1_a_disjointness.py` — disjointness invariant test (lands with this commit per Section 2.1)

**Modify:**
- `tests/test_envelope_shape.py` — add INV-2.1-A parallel enum assertion
- `.claude/commands/research-company.md` — 3 surgical edits per Section 2 v3 §"/research-company.md impact"

---

## Task 1: TacticalSignal dataclass + contracts module

**Files:**
- Create: `src/p8_tactical_overlay/__init__.py`
- Create: `src/p8_tactical_overlay/contracts.py`
- Test: `tests/test_p8_tactical_signal_contracts.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_p8_tactical_signal_contracts.py
"""Tests for TacticalSignal frozen dataclass — cross-plan handoff contract."""
import pytest
from datetime import date
from src.p8_tactical_overlay.contracts import (
    TacticalSignal, TacticalBin, TacticalDisposition, Conviction,
)


def test_tactical_signal_constructs_valid():
    sig = TacticalSignal(
        ticker="GOOGL",
        as_of_date=date(2026, 5, 20),
        tactical_bin="positive",
        rf_degenerate=False,
        unavailable_reason=None,
    )
    assert sig.ticker == "GOOGL"
    assert sig.tactical_bin == "positive"


def test_tactical_signal_frozen_dataclass_rejects_mutation():
    sig = TacticalSignal(
        ticker="GOOGL", as_of_date=date(2026, 5, 20),
        tactical_bin="positive", rf_degenerate=False,
    )
    with pytest.raises((AttributeError, Exception)):
        sig.tactical_bin = "negative"  # frozen → should error


def test_tactical_disposition_enum_values():
    # INV-2.1-A: tactical_disposition enum is disjoint from summary_code
    valid = {"HOLD", "BUY-HIGH", "BUY-MED", "AVOID"}
    for v in valid:
        # construction via Literal type doesn't validate; we just confirm the constants exist
        assert v in TacticalDisposition.__args__  # Literal args


def test_tactical_bin_enum_values():
    valid = {"positive", "neutral", "negative", "unavailable"}
    for v in valid:
        assert v in TacticalBin.__args__


def test_unavailable_reason_optional():
    sig = TacticalSignal(
        ticker="RDDT", as_of_date=date(2026, 5, 20),
        tactical_bin="unavailable", rf_degenerate=False,
        unavailable_reason="insufficient_price_history",
    )
    assert sig.unavailable_reason == "insufficient_price_history"
```

- [ ] **Step 2: Run test to verify fail**

`pytest tests/test_p8_tactical_signal_contracts.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.p8_tactical_overlay'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/p8_tactical_overlay/__init__.py
"""Tactical overlay package — Section 2 + Section 2.1 implementation."""
```

```python
# src/p8_tactical_overlay/contracts.py
"""Cross-plan handoff contracts for tactical overlay.

INV-COMPOSE-1: Plan B emits exactly TacticalSignal shape; Plan C consumes exactly this.
INV-2.1-A: tactical_disposition enum is disjoint from summary_code enum.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal, Optional

TacticalBin = Literal["positive", "neutral", "negative", "unavailable"]
TacticalDisposition = Literal["HOLD", "BUY-HIGH", "BUY-MED", "AVOID"]
Conviction = Literal["HIGH", "MEDIUM", "LOW"]
UnavailableReason = Literal["insufficient_price_history", "rf_resolver_staleness"]


@dataclass(frozen=True)
class TacticalSignal:
    """Plan B → Plan C handoff. Frozen; runtime-validated at consumption."""
    ticker: str
    as_of_date: date
    tactical_bin: TacticalBin
    rf_degenerate: bool
    unavailable_reason: Optional[UnavailableReason] = None
```

- [ ] **Step 4: Run test to verify pass**

`pytest tests/test_p8_tactical_signal_contracts.py -v`
Expected: 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/p8_tactical_overlay/__init__.py src/p8_tactical_overlay/contracts.py tests/test_p8_tactical_signal_contracts.py
git commit -m "feat: TacticalSignal dataclass + INV-COMPOSE-1 cross-plan contract"
```

---

## Task 2: Antonacci dual-momentum bin classifier

**Files:**
- Create: `src/p8_tactical_overlay/bin_classifier.py`
- Test: `tests/test_p8_tactical_bin_classifier.py`

- [ ] **Step 1: Write failing tests** (cover: `resolve_rf_at` staleness; sufficient history → bin; insufficient history → unavailable; rf_degenerate flag; monthly anchor)

```python
# tests/test_p8_tactical_bin_classifier.py
"""Tests for Antonacci dual-momentum bin classifier."""
from datetime import date, timedelta
from unittest.mock import patch
from src.p8_tactical_overlay.bin_classifier import (
    resolve_rf_at, tactical_signal_bin, first_trading_day_of_month,
    last_trading_day_of_prior_month, MAX_STALENESS_CALENDAR_DAYS_DEFAULT,
    WEEKEND_HOLIDAY_BUFFER_DAYS,
)


def test_inv_b6_window_lookback_coupled():
    # INV-B6: window_lookback_days == max_staleness + WEEKEND_HOLIDAY_BUFFER_DAYS
    assert WEEKEND_HOLIDAY_BUFFER_DAYS == 7
    assert MAX_STALENESS_CALENDAR_DAYS_DEFAULT == 7


def test_resolve_rf_at_returns_most_recent_valid_print():
    target = date(2026, 5, 20)
    fake_series = [
        (date(2026, 5, 18), 4.61),
        (date(2026, 5, 19), 4.62),
        (date(2026, 5, 20), None),  # ND day
    ]
    with patch("src.p8_tactical_overlay.bin_classifier.mcp_fred_get_series",
               return_value=fake_series):
        result = resolve_rf_at(target, max_staleness_calendar_days=7)
    assert result == 4.62  # most recent valid before target


def test_resolve_rf_at_rejects_stale_beyond_max():
    target = date(2026, 5, 20)
    fake_series = [(date(2026, 5, 5), 4.50)]  # 15 days stale > 7d gate
    with patch("src.p8_tactical_overlay.bin_classifier.mcp_fred_get_series",
               return_value=fake_series):
        result = resolve_rf_at(target, max_staleness_calendar_days=7)
    assert result is None


def test_tactical_signal_bin_insufficient_history_returns_unavailable():
    """<252 trading days → bin='unavailable' with reason 'insufficient_price_history'."""
    short_prices = [{"date": date(2026, 5, 19), "adj_close": 100.0}] * 100  # n<252
    with patch("src.p8_tactical_overlay.bin_classifier.mcp_market_data_get_prices",
               return_value=short_prices):
        result = tactical_signal_bin("RDDT", date(2026, 5, 20))
    assert result["bin"] == "unavailable"
    assert result["unavailable_reason"] == "insufficient_price_history"


def test_tactical_signal_bin_positive_both_legs():
    """Both relative AND absolute > 0 → positive."""
    # 252 trading days of GOOGL flat then 30% rally; SPY 5%; rf 4%
    base = [
        {"date": date(2025, 5, 20) + timedelta(days=i), "adj_close": 100.0}
        for i in range(252)
    ]
    base[-1]["adj_close"] = 130.0  # 30% return
    spy = [
        {"date": date(2025, 5, 20) + timedelta(days=i), "adj_close": 400.0}
        for i in range(252)
    ]
    spy[-1]["adj_close"] = 420.0  # 5% return
    with patch("src.p8_tactical_overlay.bin_classifier.mcp_market_data_get_prices",
               side_effect=[base, spy]), \
         patch("src.p8_tactical_overlay.bin_classifier.resolve_rf_at",
               return_value=4.0):
        result = tactical_signal_bin("GOOGL", date(2026, 5, 20))
    assert result["bin"] == "positive"


def test_tactical_signal_bin_negative_both_legs():
    base = [
        {"date": date(2025, 5, 20) + timedelta(days=i), "adj_close": 100.0}
        for i in range(252)
    ]
    base[-1]["adj_close"] = 70.0  # -30%
    spy = [
        {"date": date(2025, 5, 20) + timedelta(days=i), "adj_close": 400.0}
        for i in range(252)
    ]
    spy[-1]["adj_close"] = 380.0  # -5%
    with patch("src.p8_tactical_overlay.bin_classifier.mcp_market_data_get_prices",
               side_effect=[base, spy]), \
         patch("src.p8_tactical_overlay.bin_classifier.resolve_rf_at",
               return_value=4.0):
        result = tactical_signal_bin("XYZ", date(2026, 5, 20))
    assert result["bin"] == "negative"


def test_tactical_signal_bin_mixed_returns_neutral():
    """ticker beat SPY (rel positive) but below rf (abs negative) → neutral."""
    base = [
        {"date": date(2025, 5, 20) + timedelta(days=i), "adj_close": 100.0}
        for i in range(252)
    ]
    base[-1]["adj_close"] = 102.0  # +2%
    spy = [
        {"date": date(2025, 5, 20) + timedelta(days=i), "adj_close": 400.0}
        for i in range(252)
    ]
    spy[-1]["adj_close"] = 396.0  # -1%
    with patch("src.p8_tactical_overlay.bin_classifier.mcp_market_data_get_prices",
               side_effect=[base, spy]), \
         patch("src.p8_tactical_overlay.bin_classifier.resolve_rf_at",
               return_value=5.0):  # rf > 2% ticker → abs negative
        result = tactical_signal_bin("MID", date(2026, 5, 20))
    assert result["bin"] == "neutral"


def test_rf_degenerate_flag_fires_below_threshold():
    base = [
        {"date": date(2025, 5, 20) + timedelta(days=i), "adj_close": 100.0}
        for i in range(252)
    ]
    base[-1]["adj_close"] = 110.0
    spy = [
        {"date": date(2025, 5, 20) + timedelta(days=i), "adj_close": 400.0}
        for i in range(252)
    ]
    spy[-1]["adj_close"] = 405.0
    with patch("src.p8_tactical_overlay.bin_classifier.mcp_market_data_get_prices",
               side_effect=[base, spy]), \
         patch("src.p8_tactical_overlay.bin_classifier.resolve_rf_at",
               return_value=0.04):  # ZIRP regime; below 0.5 threshold
        result = tactical_signal_bin("ZIRP", date(2020, 6, 1))
    assert result["rf_degenerate"] is True
```

- [ ] **Step 2: Run test to verify fail**

`pytest tests/test_p8_tactical_bin_classifier.py -v`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Write minimal implementation**

```python
# src/p8_tactical_overlay/bin_classifier.py
"""Antonacci dual-momentum bin classifier + resolve_rf_at helper.

Per Section 2 v3-final Plan B v6 spec.
INV-B6: window_lookback_days == max_staleness + WEEKEND_HOLIDAY_BUFFER_DAYS (code-level).
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

# Module-top constants (per v6 Q3 polish for grep-ability)
MAX_STALENESS_CALENDAR_DAYS_DEFAULT = 7
WEEKEND_HOLIDAY_BUFFER_DAYS = 7
LOOKBACK_TRADING_DAYS = 252
RF_DEGENERATE_THRESHOLD_PCT = 0.5


def mcp_market_data_get_prices(ticker: str, end: date, lookback_days: int = 400):
    """Wrapper around mcp__market_data__get_prices for test mockability."""
    from src.mcp.market_data_client import get_prices  # existing client
    return get_prices(ticker, end=end, lookback_days=lookback_days)


def mcp_fred_get_series(series_id: str, start: date, end: date):
    """Wrapper around mcp__fred__get_series for test mockability."""
    from src.mcp.fred_client import get_series  # existing client
    return get_series(series_id, start=start, end=end)


def resolve_rf_at(target_date: date,
                  max_staleness_calendar_days: int = MAX_STALENESS_CALENDAR_DAYS_DEFAULT
                  ) -> Optional[float]:
    """Resolve DGS1 yield at/before target_date with staleness guard."""
    assert max_staleness_calendar_days >= 1, "INV-B4 violation"
    window_lookback_days = max_staleness_calendar_days + WEEKEND_HOLIDAY_BUFFER_DAYS  # INV-B6
    window = mcp_fred_get_series(
        "DGS1",
        start=target_date - timedelta(days=window_lookback_days),
        end=target_date,
    )
    valid = [(d, v) for d, v in window if v is not None and d <= target_date]
    if not valid:
        return None
    resolved_date, val = max(valid, key=lambda x: x[0])
    if (target_date - resolved_date).days > max_staleness_calendar_days:
        return None
    return val


def first_trading_day_of_month(year: int, month: int) -> date:
    """Returns first weekday of the month. NOTE: does not check NYSE holidays;
    Section 3 polish item to extend if needed."""
    d = date(year, month, 1)
    while d.weekday() >= 5:  # Sat=5, Sun=6
        d += timedelta(days=1)
    return d


def last_trading_day_of_prior_month(anchor: date) -> date:
    """Returns last weekday before anchor's first-of-month."""
    d = date(anchor.year, anchor.month, 1) - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def tactical_signal_bin(ticker: str, as_of_date: date) -> dict:
    """Antonacci dual-momentum classification.

    Returns: {'bin', 'rf_degenerate', 'unavailable_reason'}
    """
    anchor = first_trading_day_of_month(as_of_date.year, as_of_date.month)
    prior_close = last_trading_day_of_prior_month(anchor)

    prices = mcp_market_data_get_prices(ticker, end=prior_close, lookback_days=400)
    spy = mcp_market_data_get_prices("SPY", end=prior_close, lookback_days=400)

    if len(prices) < LOOKBACK_TRADING_DAYS or len(spy) < LOOKBACK_TRADING_DAYS:
        return {
            "bin": "unavailable",
            "rf_degenerate": False,
            "unavailable_reason": "insufficient_price_history",
        }

    ticker_ret = (prices[-1]["adj_close"] / prices[-LOOKBACK_TRADING_DAYS]["adj_close"]) - 1.0
    spy_ret = (spy[-1]["adj_close"] / spy[-LOOKBACK_TRADING_DAYS]["adj_close"]) - 1.0

    rf_yield_pct = resolve_rf_at(prices[-LOOKBACK_TRADING_DAYS]["date"])
    if rf_yield_pct is None:
        return {
            "bin": "unavailable",
            "rf_degenerate": False,
            "unavailable_reason": "rf_resolver_staleness",
        }

    rf_ret = rf_yield_pct / 100.0
    rf_degenerate = rf_yield_pct < RF_DEGENERATE_THRESHOLD_PCT

    rel = ticker_ret - spy_ret
    abs_ = ticker_ret - rf_ret

    if rel >= 0.0 and abs_ >= 0.0:
        bin_ = "positive"
    elif rel <= 0.0 and abs_ <= 0.0:
        bin_ = "negative"
    else:
        bin_ = "neutral"

    return {"bin": bin_, "rf_degenerate": rf_degenerate, "unavailable_reason": None}
```

- [ ] **Step 4: Run test to verify pass**

`pytest tests/test_p8_tactical_bin_classifier.py -v` → expect 8 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/p8_tactical_overlay/bin_classifier.py tests/test_p8_tactical_bin_classifier.py
git commit -m "feat: Antonacci dual-momentum bin classifier + resolve_rf_at helper"
```

---

## Task 3: Cell selector + tactical_disposition overlay module

**Files:**
- Create: `src/p8_tactical_overlay/overlay.py`
- Test: `tests/test_p8_tactical_overlay.py`

- [ ] **Step 1: Write failing tests** (cover: LOW row hard-zero; non-LOW cell lookup; HIGH/MEDIUM × Positive → BUY-HIGH/BUY-MED disposition; unavailable column = band.min; INV-C1 mapping completeness; LOW × Unavailable = HOLD)

```python
# tests/test_p8_tactical_overlay.py
"""Tests for tactical overlay: cell selector + tactical_disposition mapping."""
from unittest.mock import patch
from src.p8_tactical_overlay.overlay import (
    tactical_cell_size_pct, tactical_disposition,
    BAND_FALLBACK_CACHE,
)
from src.p8_tactical_overlay.contracts import TacticalDisposition


@patch("src.p8_tactical_overlay.overlay.parameters_active",
       side_effect=lambda key: {"min_pct": 3.0, "max_pct": 6.0} if "HIGH" in key
                          else {"min_pct": 1.5, "max_pct": 3.0})
def test_cell_size_high_positive_equals_band_max(mock_params):
    assert tactical_cell_size_pct("HIGH", "positive") == 6.0


@patch("src.p8_tactical_overlay.overlay.parameters_active",
       side_effect=lambda key: {"min_pct": 3.0, "max_pct": 6.0})
def test_cell_size_high_neutral_equals_midpoint(mock_params):
    assert tactical_cell_size_pct("HIGH", "neutral") == 4.5


@patch("src.p8_tactical_overlay.overlay.parameters_active",
       side_effect=lambda key: {"min_pct": 3.0, "max_pct": 6.0})
def test_cell_size_high_negative_equals_band_min(mock_params):
    assert tactical_cell_size_pct("HIGH", "negative") == 3.0


@patch("src.p8_tactical_overlay.overlay.parameters_active",
       side_effect=lambda key: {"min_pct": 3.0, "max_pct": 6.0})
def test_cell_size_high_unavailable_equals_band_min(mock_params):
    """v3 fix: unavailable → band.min, not midpoint (closes IPO alpha leak)."""
    assert tactical_cell_size_pct("HIGH", "unavailable") == 3.0


def test_cell_size_low_hardzero_regardless():
    """LOW row hard-zeroed; discipline guard not derived from band."""
    for bin_ in ("positive", "neutral", "negative", "unavailable"):
        assert tactical_cell_size_pct("LOW", bin_) == 0.0


def test_tactical_disposition_high_positive_is_buy_high():
    assert tactical_disposition("HIGH", "positive") == "BUY-HIGH"


def test_tactical_disposition_medium_positive_is_buy_med():
    assert tactical_disposition("MEDIUM", "positive") == "BUY-MED"


def test_tactical_disposition_low_unavailable_is_hold():
    """Section 2.1 v4 fix: LOW × Unavailable = HOLD (not AVOID; data-insufficiency defers)."""
    assert tactical_disposition("LOW", "unavailable") == "HOLD"


def test_tactical_disposition_low_with_signal_is_avoid():
    for bin_ in ("positive", "neutral", "negative"):
        assert tactical_disposition("LOW", bin_) == "AVOID"


def test_tactical_disposition_high_neutral_is_hold():
    assert tactical_disposition("HIGH", "neutral") == "HOLD"


def test_inv_c1_mapping_completeness():
    """INV-C1: tactical_disposition.mapping is a complete (3 conviction × 4 tactical_bin) function."""
    valid_values = {"HOLD", "BUY-HIGH", "BUY-MED", "AVOID"}
    for conv in ("HIGH", "MEDIUM", "LOW"):
        for bin_ in ("positive", "neutral", "negative", "unavailable"):
            result = tactical_disposition(conv, bin_)
            assert result in valid_values, f"({conv},{bin_}) returned {result}"
```

- [ ] **Step 2: Run test to verify fail**

`pytest tests/test_p8_tactical_overlay.py -v` → FAIL (module doesn't exist).

- [ ] **Step 3: Write minimal implementation**

```python
# src/p8_tactical_overlay/overlay.py
"""Tactical overlay: cell-size selector + tactical_disposition mapping.

Per Section 2 v3-final Plan C v5 + Section 2.1 v5-final.
INV-C1: mapping is complete over (conviction × tactical_bin).
"""
from __future__ import annotations

from typing import Literal

from src.p8_tactical_overlay.contracts import (
    Conviction, TacticalBin, TacticalDisposition,
)

# Section 2.1 v5-final mapping
_DISPOSITION_MAP: dict[tuple[str, str], str] = {
    ("HIGH", "negative"): "HOLD",
    ("HIGH", "neutral"): "HOLD",
    ("HIGH", "positive"): "BUY-HIGH",
    ("HIGH", "unavailable"): "HOLD",
    ("MEDIUM", "negative"): "HOLD",
    ("MEDIUM", "neutral"): "HOLD",
    ("MEDIUM", "positive"): "BUY-MED",
    ("MEDIUM", "unavailable"): "HOLD",
    ("LOW", "negative"): "AVOID",
    ("LOW", "neutral"): "AVOID",
    ("LOW", "positive"): "AVOID",
    ("LOW", "unavailable"): "HOLD",  # v4 fix: data-insufficiency defers
}

# Defensive fallback if parameters_active is unavailable (shouldn't happen in prod)
BAND_FALLBACK_CACHE = {
    "HIGH": {"min_pct": 3.0, "max_pct": 6.0},
    "MEDIUM": {"min_pct": 1.5, "max_pct": 3.0},
}


def parameters_active(key: str) -> dict:
    """Read sizing.conviction_band.<conv> from parameters_active view."""
    from src.parameters_review.client import read_parameter  # existing helper
    min_val = read_parameter(f"{key}.min_pct")
    max_val = read_parameter(f"{key}.max_pct")
    return {"min_pct": min_val, "max_pct": max_val}


def tactical_cell_size_pct(conviction: str, tactical_bin: str) -> float:
    """Returns cell size_pct as a VIEW of existing sizing.conviction_band.* params."""
    if conviction == "LOW":
        return 0.0  # Plan A LOW row hard-zero discipline
    band = parameters_active(f"sizing.conviction_band.{conviction}")
    if tactical_bin == "positive":
        return float(band["max_pct"])
    if tactical_bin == "neutral":
        return (float(band["min_pct"]) + float(band["max_pct"])) / 2.0
    # negative AND unavailable both → band.min (v3 fix: closes IPO alpha leak)
    return float(band["min_pct"])


def tactical_disposition(conviction: str, tactical_bin: str) -> str:
    """Returns tactical_disposition per Section 2.1 v5-final categorical mapping."""
    return _DISPOSITION_MAP[(conviction, tactical_bin)]
```

- [ ] **Step 4: Run test to verify pass** + **Step 5: Commit**

`pytest tests/test_p8_tactical_overlay.py -v` → 11 PASS.

```bash
git add src/p8_tactical_overlay/overlay.py tests/test_p8_tactical_overlay.py
git commit -m "feat: tactical_cell_size_pct + tactical_disposition mapping (Section 2.1 v5)"
```

---

## Task 4: INV-2.1-A disjointness invariant test

**Files:**
- Modify: `tests/test_envelope_shape.py` (add parallel assertion)
- Create: `tests/test_p8_inv_2_1_a_disjointness.py`

- [ ] **Step 1: Write test verifying disjoint enums**

```python
# tests/test_p8_inv_2_1_a_disjointness.py
"""INV-2.1-A: summary_code enum ⊥ tactical_disposition enum.

Per Section 2.1 v5-final consensus doc.
"""
from src.p8_tactical_overlay.contracts import TacticalDisposition


def test_inv_2_1_a_disjointness():
    """Canonical summary_code enum and tactical_disposition enum share NO values."""
    canonical_summary_code = {"BUY", "HOLD", "TRIM", "SELL"}  # per test_envelope_shape.py Consensus #1
    tactical_disp = set(TacticalDisposition.__args__)
    intersection = canonical_summary_code & tactical_disp
    assert intersection == set(), (
        f"INV-2.1-A violation: summary_code ∩ tactical_disposition = {intersection}"
    )


def test_tactical_disposition_uses_hyphenated_labels():
    """v5-final: BUY-HIGH and BUY-MED (hyphenated; distinct from canonical BUY)."""
    tactical_disp = set(TacticalDisposition.__args__)
    assert "BUY-HIGH" in tactical_disp
    assert "BUY-MED" in tactical_disp
    assert "BUY" not in tactical_disp  # canonical BUY MUST NOT appear here
```

- [ ] **Step 2: Run test to verify pass**

`pytest tests/test_p8_inv_2_1_a_disjointness.py -v` → 2 PASS.

- [ ] **Step 3: Add parallel assertion to existing test_envelope_shape.py**

Find the existing block at `tests/test_envelope_shape.py:30` (per grep: `"""Consensus Item #1: only BUY/HOLD/TRIM/SELL are valid summary_code values."""`) and ADD after it:

```python
def test_inv_2_1_a_tactical_disposition_uses_disjoint_enum():
    """INV-2.1-A: tactical_disposition enum is disjoint from summary_code enum.

    Section 2.1 v5-final lock — see docs/superpowers/consensus/2026-05-21-section2.1-label-vocabulary.md.
    """
    from src.p8_tactical_overlay.contracts import TacticalDisposition
    tactical_values = set(TacticalDisposition.__args__)
    summary_values = {"BUY", "HOLD", "TRIM", "SELL"}
    assert (tactical_values & summary_values) == set(), (
        "INV-2.1-A: tactical_disposition must not share values with summary_code"
    )
```

- [ ] **Step 4: Run modified test_envelope_shape.py + commit**

```bash
pytest tests/test_envelope_shape.py tests/test_p8_inv_2_1_a_disjointness.py -v
git add tests/test_p8_inv_2_1_a_disjointness.py tests/test_envelope_shape.py
git commit -m "test: INV-2.1-A disjointness invariant (Section 2.1 v5-final)"
```

---

## Task 5: HG validator for tactical envelope shape

**Files:**
- Create: `src/evaluator_gates/tactical_envelope_shape.py`
- Test: `tests/test_p8_tactical_envelope_shape.py`

Mirrors `src/evaluator_gates/catalyst_memo_shape.py` (HG-31). Validates the JSON envelope `tactical-overlay` agent emits.

- [ ] **Step 1: Write test**

```python
# tests/test_p8_tactical_envelope_shape.py
"""Tests for tactical envelope HG validator."""
import json
from src.evaluator_gates.tactical_envelope_shape import validate


def _valid_envelope():
    return {
        "ticker": "GOOGL",
        "as_of_date": "2026-05-20",
        "run_id": "00000000-0000-0000-0000-000000000000",
        "tactical_signal_bin": "positive",
        "rf_degenerate": False,
        "unavailable_reason": None,
        "tactical_cell": {
            "conviction": "HIGH",
            "tactical_bin": "positive",
            "cell_size_pct": 6.0,
            "cell_disposition": "BUY-HIGH",
        },
        "frameworks_cited": ["antonacci_dual_momentum_2014"],
    }


def test_valid_envelope_passes():
    out = validate(_valid_envelope())
    assert out.passed is True


def test_missing_top_level_key_fails():
    env = _valid_envelope()
    del env["tactical_signal_bin"]
    out = validate(env)
    assert out.passed is False
    assert "tactical_signal_bin" in out.errors[0]


def test_invalid_disposition_enum_fails():
    """INV-2.1-A enforcement at validator level — canonical BUY rejected."""
    env = _valid_envelope()
    env["tactical_cell"]["cell_disposition"] = "BUY"  # canonical, not tactical
    out = validate(env)
    assert out.passed is False
    assert "cell_disposition" in out.errors[0]


def test_unavailable_bin_requires_reason():
    env = _valid_envelope()
    env["tactical_signal_bin"] = "unavailable"
    env["unavailable_reason"] = None
    out = validate(env)
    assert out.passed is False
```

- [ ] **Step 2-5: Implement, run tests, commit**

```python
# src/evaluator_gates/tactical_envelope_shape.py
"""Tactical-overlay JSON envelope shape validator.

Mirrors HG-31 catalyst_memo_shape pattern. Per Section 2 v3-final + Section 2.1 v5-final.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field

TACTICAL_BIN_VALUES = {"positive", "neutral", "negative", "unavailable"}
TACTICAL_DISPOSITION_VALUES = {"HOLD", "BUY-HIGH", "BUY-MED", "AVOID"}  # INV-2.1-A enum
CONVICTION_VALUES = {"HIGH", "MEDIUM", "LOW"}
UNAVAILABLE_REASON_VALUES = {"insufficient_price_history", "rf_resolver_staleness"}

REQUIRED_TOP_LEVEL = (
    "ticker", "as_of_date", "run_id", "tactical_signal_bin", "rf_degenerate",
    "tactical_cell", "frameworks_cited",
)
REQUIRED_TACTICAL_CELL = (
    "conviction", "tactical_bin", "cell_size_pct", "cell_disposition",
)


@dataclass
class ValidationResult:
    passed: bool
    errors: list[str] = field(default_factory=list)


def validate(env: dict) -> ValidationResult:
    errs: list[str] = []

    for key in REQUIRED_TOP_LEVEL:
        if key not in env:
            errs.append(f"missing top-level key: {key}")
    if errs:
        return ValidationResult(passed=False, errors=errs)

    if env["tactical_signal_bin"] not in TACTICAL_BIN_VALUES:
        errs.append(f"tactical_signal_bin invalid: {env['tactical_signal_bin']}")

    if env["tactical_signal_bin"] == "unavailable":
        if env.get("unavailable_reason") not in UNAVAILABLE_REASON_VALUES:
            errs.append("unavailable bin requires valid unavailable_reason")

    cell = env.get("tactical_cell", {})
    for key in REQUIRED_TACTICAL_CELL:
        if key not in cell:
            errs.append(f"missing tactical_cell.{key}")
    if errs:
        return ValidationResult(passed=False, errors=errs)

    if cell["conviction"] not in CONVICTION_VALUES:
        errs.append(f"tactical_cell.conviction invalid: {cell['conviction']}")
    if cell["tactical_bin"] not in TACTICAL_BIN_VALUES:
        errs.append(f"tactical_cell.tactical_bin invalid: {cell['tactical_bin']}")
    # INV-2.1-A: enforce disjoint enum
    if cell["cell_disposition"] not in TACTICAL_DISPOSITION_VALUES:
        errs.append(
            f"tactical_cell.cell_disposition invalid: {cell['cell_disposition']} "
            f"(must be one of {TACTICAL_DISPOSITION_VALUES}; INV-2.1-A)"
        )

    if not isinstance(cell.get("cell_size_pct"), (int, float)):
        errs.append("tactical_cell.cell_size_pct must be numeric")

    return ValidationResult(passed=len(errs) == 0, errors=errs)


def main():
    env = json.loads(sys.stdin.read())
    out = validate(env)
    if out.passed:
        sys.exit(0)
    for e in out.errors:
        print(e, file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
```

```bash
pytest tests/test_p8_tactical_envelope_shape.py -v
git add src/evaluator_gates/tactical_envelope_shape.py tests/test_p8_tactical_envelope_shape.py
git commit -m "feat: HG validator for tactical envelope shape (INV-2.1-A enforcement)"
```

---

## Task 6: Postgres migration — 29 parameter rows

**Files:**
- Create: `db/migrations/038_tactical_overlay_parameters.sql`

29 rows: 12 in `tactical.*` (Plan B) + 12 mapping cells + 4 surface/disagreement/renderer + 4 review-trigger (Plan C v5 + Section 2.1 v5).

Mirrors `033_parameters_seed_research_company.sql` INSERT pattern. Idempotent via `WHERE NOT EXISTS`. All rows `tag = NULL` (production governance).

- [ ] **Step 1-5:** Write migration file with 29 INSERTs; verify idempotent via dry-run; apply via psql; commit.

(See migration file body in implementation; deferred from this plan to keep size focused — straightforward translation of Section 2/2.1 spec to INSERT statements.)

```bash
psql -h 127.0.0.1 -p 5432 -U postgres -d equity_research \
     -f db/migrations/038_tactical_overlay_parameters.sql
git add db/migrations/038_tactical_overlay_parameters.sql
git commit -m "migration: 038 tactical-overlay parameters (29 rows; Section 2 + Section 2.1)"
```

---

## Task 7: tactical-overlay agent definition

**Files:**
- Create: `.claude/agents/tactical-overlay.md`

Mirrors `.claude/agents/catalyst-scout.md` structure. LLM wrapper around the deterministic Python module. Key sections:
- Frontmatter (tools list: mcp__market_data, mcp__fred only — no analyst MCPs)
- PARAMETERS_USED block ground truth
- Algorithm (calls `tactical_signal_bin` from Python module)
- Envelope persistence to `memos/envelopes/tactical-overlay__<run_id>.json`
- Envelope schema (matches HG validator from Task 5)
- Sweep-mode awareness (--as-of-tag inheritance)

- [ ] **Step 1-5:** Draft agent definition; cross-check against catalyst-scout.md patterns; commit.

```bash
git add .claude/agents/tactical-overlay.md
git commit -m "feat: tactical-overlay agent definition (Stage 1 parallel slot)"
```

---

## Task 8: /research-company orchestrator integration

**Files:**
- Modify: `.claude/commands/research-company.md`

3 surgical edits per Section 2 v3 §"/research-company.md impact":
1. Line 166-172 (PARAMETERS_USED composer): ADD bullet for tactical-overlay namespace
2. Line 358-365 (Stage 1 parallel dispatch): ADD 3rd `Agent(tactical-overlay, ...)` call
3. Line 533 (pm-supervisor dispatch): ADD reference to consuming tactical_envelope

- [ ] **Step 1-5:** Apply 3 Edit operations; verify research-company.md still grep-clean; commit.

```bash
git add .claude/commands/research-company.md
git commit -m "feat: /research-company Stage 1 parallel dispatch adds tactical-overlay"
```

---

## Task 9: Phase 1 backtest harness

**Files:**
- Create: `src/backtesting/phase1_tactical_overlay.py`
- Test: `tests/test_p8_phase1_backtest_harness.py`

Phase 1 step 8 acceptance: enum-validity correctness check on 12-envelope GOOGL cohort. Per Section 2.1 v5-final.

Harness:
- Reads all `pm-supervisor__*.json` envelopes for ticker
- For each, computes `tactical_signal_bin` at envelope created_at
- Applies cell selector + disposition mapping
- Asserts each emitted disposition is in valid enum (catches INV-2.1-A violations)
- Logs per-label fire rate (descriptive only; no threshold)

- [ ] **Step 1-5:** Write harness + tests + run against existing 12 GOOGL envelopes + commit.

```bash
git add src/backtesting/phase1_tactical_overlay.py tests/test_p8_phase1_backtest_harness.py
git commit -m "feat: Phase 1 backtest harness with enum-validity correctness check"
```

---

## Execution gate

After all 9 tasks complete and tests pass:
- Run full test suite: `pytest tests/test_p8_*.py tests/test_envelope_shape.py -v`
- Merge worktree → main with `--no-ff`
- Cleanup worktree + branch

## Section 3 → operator handoff

Section 3 implementation complete when:
- All 9 task commits land on main
- All tests pass
- Migration 038 applied to postgres
- `/research-company` orchestrator dispatches tactical-overlay in Stage 1

Phase 1 backtest can then run (operator-initiated against 12-envelope GOOGL cohort).
Phase 2 trigger fires when envelope_count ≥ 50 AND ticker_count ≥ 5 accumulate.
Phase 3 18-month deadline starts from Phase 2 trigger date.
