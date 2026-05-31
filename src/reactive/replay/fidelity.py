"""Replay Harness: the champion-reproduction fidelity comparator (PURE).

The champion-reproduction precondition the consumer (`walkforward-tuning-loop`)
reads before trusting any candidate number (requirements.md Requirement 7).
This module is a **pure comparator** — no I/O, no DataPort, and it MUST NOT
import the `simulator` (design.md `fidelity` block, lines 210-213: "fidelity
does **not** import simulator ... the harness orchestrates both"). The harness
re-simulates the champion's own pinned version, then passes the resulting
simulated records + the champion's recorded fills here; this module reconstructs
the recorded-champion P&L and renders the three-valued verdict.

Verdict (design lines 210-213; Requirement 7 AC 7.1/7.2/7.3):
  * ``"pass"``          — recorded vs simulated champion P&L agree within
                          ``tolerance`` (7.1).
  * ``"fail"``          — they diverge beyond ``tolerance`` → engine distrust;
                          the consumer withholds promotion (7.2).
  * ``"not_evaluable"`` — the recorded-champion baseline is absent or too sparse
                          to form ANY round trip (e.g. paper cold-start) → DISTINCT
                          from ``"fail"`` so the consumer treats a sparse baseline
                          differently from an engine defect (7.3).

Recorded-champion P&L reconstruction (simulator **Core-algorithms #5**,
design.md line 205): per ``(day, symbol)`` under the §16.1
one-position-per-symbol-per-day invariant, **FIFO-pair** entry fills against
that day's flatten fills (handling partial / multi-row fills by volume); each
matched leg contributes ``(exit − entry) × min(volume) × dir`` where
``dir = +1`` for LONG and ``−1`` for SHORT. The fill rows carry no
``position_id``, so pairing relies on the one-position invariant. **If a
``(day, symbol)`` group is NOT a single net round trip** (unmatched or surplus
legs — entry volume ≠ exit volume), reconstruction is ambiguous and this module
**aborts** by raising :class:`PairingAmbiguityError` rather than silently
undercounting (design line 205: "aborts with a pairing-ambiguity signal ...
never a silent undercount"). ``FidelityResult.status`` is a frozen three-valued
``Literal`` in ``types.py`` (which is outside this task's boundary), so the
abort is a TYPED EXCEPTION, never a fourth status.

The ``recorded_fills`` contract (harness-synthesized joined dicts)
-----------------------------------------------------------------
``compare``'s signature is exactly ``(simulated_records, recorded_fills,
tolerance)`` (design line 213) — there is no separate ``decisions`` parameter.
The champion's recorded fills live as ``kind=fill`` rows in
``decision_process_trace`` whose JSONB ``trace`` carries ``actual_fill_price`` /
``fill_volume``; the position's ``symbol`` + ``direction`` (LONG/SHORT) live on
the **linked decision** row (joined by ``parent_trace_id``). Neither the
telemetry schema nor the fixture builders carry ``symbol`` or a buy/sell
``side`` as typed fields — they are decision-linked JSONB. The **harness**
performs that decision→fill join before calling ``compare``, so each
``recorded_fills`` entry is a plain dict:

    {
      "day": str,                  # ISO date — the §16.1 grouping key
      "symbol": str,               # from the linked decision (JSONB trace)
      "direction": "LONG"|"SHORT", # the position direction (decision trace)
      "side": "BUY"|"SELL",        # the venue action of THIS leg (entry vs exit)
      "actual_fill_price": float,  # fill `trace.actual_fill_price`
      "fill_volume": float,        # fill `trace.fill_volume`
    }

Entry-vs-exit classification: a LONG is opened by ``BUY`` and flattened by
``SELL``; a SHORT is opened by ``SELL`` and flattened by ``BUY``.

Known basis asymmetry (revalidation trigger, not a bug)
-------------------------------------------------------
The two compared P&L sides are on slightly different bases, by construction:
the **recorded** side is **price-only** — Core-algorithms #5 (design line 205)
is ``(exit − entry) × min(vol) × dir`` with no dividend term, because the fill
rows are the *sole* baseline (design lines 221-222) and carry no dividend data.
The **simulated** side, ``OutcomeRecord.total_return_pnl``, is **price P&L +
same-day cash dividends** (types.py line 127; Core-algorithms #3 line 203). On a
champion position-day with a cash dividend the simulated total carries the
dividend and the recorded total does not, which can inflate ``|divergence|`` and
flip ``pass`` → ``fail``. This cannot be made symmetric here — ``OutcomeRecord``
exposes no price-only field to strip the dividend from, and the recorded baseline
is structurally fill-only. The error direction is **conservative** (a false
``fail`` withholds promotion, consistent with P7). If dividend-day fidelity
needs to be exact, the fix lives upstream (a price-only P&L field on the
outcome record or a dividend-aware recorded baseline), not in this comparator.

Pure leaf (P1 / design §Allowed Dependencies): stdlib + ``types`` only — no
httpx, no MCP, no DB, no ``simulator`` import, no consumer-spec import.

Requirements: 7.1, 7.2, 7.3.
"""

from __future__ import annotations

from collections import defaultdict

from src.reactive.replay.types import FidelityResult, OutcomeRecord

# Floating-point slack for the per-group volume-balance check (entry == exit).
# Small relative to any realistic share/contract volume; keeps round-trip
# detection from spuriously flagging ambiguity on float noise.
_VOLUME_EPS = 1e-9


class PairingAmbiguityError(Exception):
    """Recorded fills for a ``(day, symbol)`` group are not a single round trip.

    Raised by :func:`compare` when a populated ``(day, symbol)`` group cannot be
    FIFO-paired into one net round trip — unmatched or surplus legs, i.e. entry
    volume ≠ exit volume (design Core-algorithms #5). The §16.1 one-position
    invariant guarantees one round trip per group; a violation means the recorded
    champion P&L cannot be reconstructed without undercounting, so the comparator
    ABORTS rather than returning a (silently wrong) verdict. This is a
    revalidation trigger surfaced to the consumer: if concurrent same-symbol
    intraday positions ever become possible, fill rows need a ``position_id``
    and this pairing assumption must be revisited.

    ``status`` cannot express this (it is a frozen 3-valued ``Literal`` in
    ``types.py``, outside this task's boundary), hence a typed exception. It is
    DISTINCT from ``not_evaluable``: ``not_evaluable`` means the baseline is
    absent/too-sparse to pair at all; this means the baseline is populated but
    structurally un-pairable.
    """


def _dir_sign(direction: str) -> int:
    """``+1`` for LONG, ``−1`` for SHORT (design Core-algorithms #3/#5)."""
    if direction == "LONG":
        return 1
    if direction == "SHORT":
        return -1
    raise PairingAmbiguityError(
        f"recorded fill carries an un-pairable direction {direction!r} "
        "(expected 'LONG' or 'SHORT')"
    )


def _is_entry(direction: str, side: str) -> bool:
    """A leg is an ENTRY iff it opens the position for its direction.

    LONG opens on BUY, SHORT opens on SELL; the opposite side flattens (§16.1).
    """
    if direction == "LONG":
        return side == "BUY"
    if direction == "SHORT":
        return side == "SELL"
    raise PairingAmbiguityError(
        f"recorded fill carries an un-pairable direction {direction!r}"
    )


def _group_pnl(day: str, symbol: str, legs: list[dict]) -> float:
    """FIFO-pair one ``(day, symbol)`` group's legs into a single round trip.

    Splits the group into entry and exit queues (preserving order for FIFO),
    then pairs them off by volume: each matched slice contributes
    ``(exit − entry) × min(volume) × dir``. The §16.1 one-position invariant
    means the whole group must net to ONE round trip — total entry volume must
    equal total exit volume. Any imbalance (unmatched/surplus legs, partial
    volume mismatch) raises :class:`PairingAmbiguityError`.
    """
    dir_sign = _dir_sign(legs[0]["direction"])

    entries: list[tuple[float, float]] = []  # (price, remaining_volume), FIFO
    exits: list[tuple[float, float]] = []
    for leg in legs:
        direction = leg["direction"]
        side = leg["side"]
        price = float(leg["actual_fill_price"])
        volume = float(leg["fill_volume"])
        if _is_entry(direction, side):
            entries.append((price, volume))
        else:
            exits.append((price, volume))

    total_entry_vol = sum(v for _, v in entries)
    total_exit_vol = sum(v for _, v in exits)

    # §16.1 one-position invariant: a populated group must be a balanced round
    # trip. Unmatched (one-sided) or surplus (entry_vol != exit_vol) legs are a
    # non-round-trip day → abort, never undercount.
    if not entries or not exits or abs(total_entry_vol - total_exit_vol) > _VOLUME_EPS:
        raise PairingAmbiguityError(
            f"({day}, {symbol}) is not a single round trip: "
            f"entry_volume={total_entry_vol} exit_volume={total_exit_vol} "
            f"(entries={len(entries)}, exits={len(exits)}); "
            "unmatched/surplus legs — recorded champion P&L is un-reconstructable"
        )

    # FIFO-pair entry slices against exit slices by min volume.
    pnl = 0.0
    ei = xi = 0
    entry_price, entry_rem = entries[0]
    exit_price, exit_rem = exits[0]
    while True:
        matched = min(entry_rem, exit_rem)
        pnl += (exit_price - entry_price) * matched * dir_sign
        entry_rem -= matched
        exit_rem -= matched
        if entry_rem <= _VOLUME_EPS:
            ei += 1
            if ei >= len(entries):
                break
            entry_price, entry_rem = entries[ei]
        if exit_rem <= _VOLUME_EPS:
            xi += 1
            if xi >= len(exits):
                break
            exit_price, exit_rem = exits[xi]
    return pnl


def _recorded_champion_pnl(recorded_fills: list[dict]) -> float:
    """Reconstruct the total recorded-champion P&L (Core-algorithms #5).

    Groups the harness-joined fill dicts by ``(day, symbol)`` and sums each
    group's single-round-trip P&L. Raises :class:`PairingAmbiguityError` if any
    group is not a clean round trip.
    """
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for leg in recorded_fills:
        groups[(leg["day"], leg["symbol"])].append(leg)

    total = 0.0
    for (day, symbol), legs in groups.items():
        total += _group_pnl(day, symbol, legs)
    return total


def _has_any_round_trip(recorded_fills: list[dict]) -> bool:
    """True iff at least one ``(day, symbol)`` group has both an entry and an exit.

    The 7.3 ``not_evaluable`` gate: an empty baseline, or one too sparse to form
    ANY round trip (e.g. only lone entries, paper cold-start), is not-evaluable
    — distinct from a populated-but-unbalanced day, which is a pairing abort.
    """
    sides_seen: dict[tuple[str, str], set[bool]] = defaultdict(set)
    for leg in recorded_fills:
        key = (leg["day"], leg["symbol"])
        sides_seen[key].add(_is_entry(leg["direction"], leg["side"]))
    return any(True in seen and False in seen for seen in sides_seen.values())


def compare(
    simulated_records: list[OutcomeRecord],
    recorded_fills: list[dict],
    tolerance: float,
) -> FidelityResult:
    """Compare simulated-champion P&L to the recorded-champion baseline (R7).

    Pure (no I/O, no simulator import) — the harness supplies both sides
    (design lines 210-213). Steps, ordered so the three non-pass outcomes do not
    collide:

      1. **Sparse-baseline gate (7.3):** if ``recorded_fills`` is empty or too
         sparse to contain ANY round trip → ``not_evaluable`` (BEFORE any
         pairing). This is the clean line vs the abort: empty/insufficient here,
         populated-but-unbalanced raises below.
      2. **Recorded P&L reconstruction (Core-algorithms #5):** FIFO-pair each
         ``(day, symbol)`` group into one round trip and sum. A non-round-trip
         group raises :class:`PairingAmbiguityError`.
      3. **Verdict (7.1/7.2):** ``pass`` iff
         ``abs(simulated_total − recorded_total) <= tolerance`` else ``fail``.
         The comparison is on the AGGREGATE total (R7.1 is ledger-*total*
         reproduction), with an ABSOLUTE tolerance (the plain reading of "within
         a configured tolerance"); the magnitude is surfaced in ``detail``.

    Raises:
        PairingAmbiguityError: a populated ``(day, symbol)`` group is not a
            single net round trip (unmatched/surplus legs) — never a silent
            undercount.
    """
    # --- 1. Sparse-baseline gate (7.3) — distinct from fail ----------------
    if not recorded_fills or not _has_any_round_trip(recorded_fills):
        return FidelityResult(
            status="not_evaluable",
            detail=(
                "recorded-champion baseline absent or too sparse to form any "
                f"round trip ({len(recorded_fills)} recorded fill(s)); "
                "fidelity not-evaluable (e.g. paper cold-start) — distinct from "
                "an engine defect (R7.3)"
            ),
        )

    # --- 2. Reconstruct recorded-champion P&L (Core-algorithms #5) ---------
    #     (raises PairingAmbiguityError on a non-round-trip group)
    recorded_total = _recorded_champion_pnl(recorded_fills)

    # --- 3. Simulated-champion P&L: sum the per-period OutcomeRecord P&L ----
    simulated_total = sum(r.total_return_pnl for r in simulated_records)

    # --- 4. Verdict (7.1 pass / 7.2 fail) ----------------------------------
    divergence = abs(simulated_total - recorded_total)
    if divergence <= tolerance:
        return FidelityResult(
            status="pass",
            detail=(
                f"champion reproduced within tolerance: "
                f"simulated={simulated_total:.6f} recorded={recorded_total:.6f} "
                f"|divergence|={divergence:.6f} <= tolerance={tolerance:.6f} (R7.1)"
            ),
        )
    return FidelityResult(
        status="fail",
        detail=(
            f"champion-reproduction tolerance breached: "
            f"simulated={simulated_total:.6f} recorded={recorded_total:.6f} "
            f"|divergence|={divergence:.6f} > tolerance={tolerance:.6f} "
            "→ engine distrust; consumer withholds promotion (R7.2)"
        ),
    )


__all__ = ["compare", "PairingAmbiguityError"]
