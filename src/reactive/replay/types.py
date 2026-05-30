"""Replay Harness: the owned in-memory contract types (dependency root).

The single source of the Replay Harness's data contracts — the candidate
config knobs, the replay window, the per-fill record, the pinned per-period
``OutcomeRecord``, the wrapped ``ReplayResult``, the champion-reproduction
``FidelityResult``, and the ``DataPort`` point-in-time fetch protocol. Per the
design "File Structure Plan" (`types.py` is the dependency root) and "Data
Models → Owned (in-memory contracts only — no DB table; read-only consumer)":
pure types, no logic. This module satisfies Requirement 1 AC 1.3 (a candidate
expressed as a reactive param snapshot and/or survival parameters and/or a
code version) and Requirement 8 AC 8.1 (the per-period outcome record carrying
the candidate's decisions, fills with prices, total-return P&L, survival
events, predicted probabilities, and realized labels).

Pure leaf (P1 / design §Allowed Dependencies): stdlib + typing only — no
httpx, no MCP, no DB, no consumer-spec imports. Dependency direction is strict
(design §Dependency direction): `types -> data_client -> features_adapter ->
simulator -> outcomes -> harness`; `fidelity` imports `types` only. Nothing
here imports upward and nothing imports a consumer spec (`walkforward-tuning-loop`).

Canonical-vocabulary reuse (P9): ``Decision`` is the landed reactive decision
vocabulary (`src.reactive.types`); ``Label`` is the landed calibration label
(`src.calibration.scorer`). Both are imported, never re-declared — the
harness↔tuner seam pins ``OutcomeRecord`` so it cannot drift. ``ParamSnapshot``
is the landed reactive parameter snapshot (`src.reactive.params`, sanctioned in
design §Allowed Dependencies). ``survival_parameters`` is typed ``Any`` because
``src.survival`` is DESIGNED-not-landed (design §Allowed Dependencies "Drive
(DESIGNED — stub in tests, revalidate on landing)"); a forward-ref to the
missing module would make ``get_type_hints(Candidate)`` raise. Re-typing it to
the landed ``SurvivalParameters`` is the revalidation trigger when survival
lands.

Frozen dataclasses throughout so the determinism contract (R9.1: identical
config + window + inputs → identical record) holds and nothing mutates a
returned record. ``DataPort`` is a ``runtime_checkable`` ``typing.Protocol``
(design "Data Models": "satisfied by `data_client` in prod and a fixture in
tests"); the real client (later task) and test fixtures structurally implement
it — injection is the R9.2 inner-ring isolation seam.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol, runtime_checkable

from src.calibration.scorer import Label
from src.reactive.params import ParamSnapshot
from src.reactive.types import Decision


# --- Candidate config (R1.3: param snapshot and/or survival and/or code) --


@dataclass(frozen=True)
class Candidate:
    """One candidate trading config — the atomic unit the tuner backtests (R1.3).

    All three knobs are optional so the tuner can vary the reactive parameters
    (`param_snapshot`), the survival-gate parameters (`survival_parameters`),
    a code version (`code_version` — the code track may be deferred for v0.1
    per `walkforward-tuning-loop`), or any combination.

    `survival_parameters` is typed ``Any`` until ``src.survival`` lands
    (design §Allowed Dependencies "Drive (DESIGNED)"); re-type it to the landed
    ``SurvivalParameters`` then — a shape revalidation trigger (R10.3).
    """

    param_snapshot: ParamSnapshot | None = None
    survival_parameters: Any | None = None
    code_version: str | None = None


# --- Replay window (R1.2: caller supplies; harness imposes no CV scheme) --


@dataclass(frozen=True)
class ReplayWindow:
    """One historical window to replay (R1.2).

    `start` / `end` are ISO dates bounding the replay; `tickers` is the symbol
    universe for the window. The consumer (`walkforward-tuning-loop`) supplies
    one per CPCV partition — the harness imposes no cross-validation scheme.
    """

    start: str
    end: str
    tickers: list[str]


# --- Fill record (R6.1: counterparty prices, not mid) ---------------------


@dataclass(frozen=True)
class Fill:
    """One simulated order fill at counterparty (bid/ask or traded) prices (R6.1).

    `side` is the trade side; `price` the counterparty fill price (never mid);
    `volume` the filled quantity (float, matching the `Bar.volume` convention);
    `ts` the ISO fill timestamp.
    """

    side: str
    price: float
    volume: float
    ts: str


# --- Per-period outcome record (R8.1: the pinned harness↔tuner seam) -------


@dataclass(frozen=True)
class OutcomeRecord:
    """The per-period record the tuner scores — EXACTLY the 9 pinned fields (R8.1).

    Pinned by the design "Data Models → Owned (in-memory contracts only)" block
    so the harness↔tuner seam cannot drift: `walkforward-tuning-loop`'s
    `metric`/`oos` import and reference this shape (no re-declaration). The
    harness computes no metric, calibration, or gate (R8.2) — these are the raw
    outcomes the consumer scores.

    Fields (order is load-bearing — the seam is positional-stable):
      - `period`: ISO date of the trading day.
      - `symbol`: the traded name.
      - `decision`: the candidate's act-or-hold call (reactive `Decision` vocab).
      - `predicted_probability`: the softmax P at fire (calibration input).
      - `fills`: counterparty-price fills for the day.
      - `total_return_pnl`: price P&L + same-day cash dividends (R5.1).
      - `survival_events`: e.g. ["admit_reject","stop_hit","flatten","safe_mode"].
      - `realized_outcome`: the day's realized round-trip return (calibration target).
      - `realized_label`: the 4-bin calibration `Label` (BUY/HOLD/TRIM/SELL).
    """

    period: str
    symbol: str
    decision: Decision
    predicted_probability: float
    fills: list[Fill]
    total_return_pnl: float
    survival_events: list[str]
    realized_outcome: float
    realized_label: Label


# --- Champion-reproduction fidelity verdict (R7.1/7.2/7.3) ----------------


@dataclass(frozen=True)
class FidelityResult:
    """The champion-reproduction precondition verdict (R7).

    `status` is the three-valued outcome:
      - `"pass"`: simulated-champion P&L reproduces the recorded ledger within
        the configured tolerance (R7.1).
      - `"fail"`: tolerance not met → engine distrust; the consumer withholds
        promotion (R7.2).
      - `"not_evaluable"`: the champion's recorded fill baseline is absent or
        insufficient (e.g. paper cold-start) → distinct from `"fail"`, so the
        consumer treats sparse baseline differently from an engine defect (R7.3).

    `detail` is the human-readable explanation (tolerance breach magnitude,
    sparse-baseline reason); the pure comparator `fidelity.compare` (later task)
    populates it.
    """

    status: Literal["pass", "fail", "not_evaluable"]
    detail: str


# --- Replay result wrapper (R1.1 + R7) ------------------------------------


@dataclass(frozen=True)
class ReplayResult:
    """What `replay_candidate` returns: the per-period records + the fidelity verdict.

    `records` is one `OutcomeRecord` per trading day (R1.1); `fidelity` is the
    champion-reproduction precondition the consumer reads before trusting any
    candidate number (R7).
    """

    records: list[OutcomeRecord]
    fidelity: FidelityResult


# --- Point-in-time data port (R4 / R9.2 injection seam) -------------------


@runtime_checkable
class DataPort(Protocol):
    """Point-in-time historical-data fetch protocol (design `data_client`).

    Satisfied by the real `data_client` in production and by a fixture provider
    in tests — the `simulator` receives one by injection, which is the R9.2
    inner-ring isolation seam (no live feed / DB) and what lets R2.2 mid-loop
    fetches for divergent names work on demand.

    Every method is point-in-time bounded: it must never return data timestamped
    after the requested instant for a decision input (R4.1). Exact argument
    names / return shapes are finalized when `data_client` implements this
    (design `data_client` "signatures finalized at implementation"); these are
    the five named fetch methods the design pins.
    """

    def fetch_daily_bars(
        self, symbol: str, start: str, end: str
    ) -> list[dict]:
        """As-of daily OHLCV bars (`adjusted=false`) over [start, end] (R4.1/4.2)."""
        ...

    def fetch_intraday(self, symbol: str, day: str) -> list[dict]:
        """The intraday price path for `day` — fills + stop-hit determination (R6.2)."""
        ...

    def fetch_quotes(self, symbol: str, ts: str) -> dict:
        """The NBBO quote as-of `ts` for counterparty-price fills (R6.1)."""
        ...

    def fetch_corporate_actions(
        self, symbol: str, start: str, end: str
    ) -> list[dict]:
        """Splits + cash dividends over [start, end] for total-return P&L (R5.1)."""
        ...

    def fetch_rf_yield(self, day: str) -> float:
        """The risk-free yield as-of `day` (FRED) — a feature input."""
        ...
