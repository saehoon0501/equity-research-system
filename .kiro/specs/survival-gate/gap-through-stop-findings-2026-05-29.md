# Gap-Through-Stop — Deep-Research Findings (2026-05-29)

**Source:** `/deep-research` (100 agents, 18 sources, 25 claims verified → **25 confirmed, 0 killed**). This is the second pass on the residual the first pass could not crack (§11.6 / §12.2 / §16). Resolves it to a **decision-grade conclusion via strong convergent analogy** — *not* a Gate-primary smoking gun (Gate's TradFi User Agreement / per-product terms returned HTTP 403, unretrieved).

## Conclusion (decision-grade)
**Gap-through-stop materializes for Gate TradFi US-stock CFDs, and the downside is effectively UNBOUNDED.**
- Gate runs the **MT5 CFD model with fixed traditional-market sessions + closures** (Gate-official, launch release; overnight swap applies through closures → the non-traded windows that produce gaps).
- On MT5 venues, **both a regular stop-loss AND the account-level 50%-margin-level stop-out are NON-guaranteed**: on trigger they become market orders filled at the **next-available bid/ask**, so a weekend/overnight/halt reopen gap realizes loss **exceeding** the stop / liquidation distance. *(MT5-general — OANDA, EBC, MetaTrader5 docs — + closest comparable venue, Bybit MT5 TradFi: "stop becomes a market order… subject to slippage"; liquidation "closed at the market bid/ask price.")*
- **No GSLO, no max-loss cap, no pre-emptive gap controls** (raised weekend margin, pre-event leverage cuts) found — Gate-official or comparable. **Equity-CFD leverage is fixed at 5x and cannot be user-reduced** → the standard self-mitigations are unavailable.
- Combined with **no negative-balance protection**, a gap-through can push equity **negative**; weekend/holiday/overnight closures are the **primary path**. The crypto Unified-Account insurance fund does **NOT** extend to TradFi (contamination guard — confirmed 3-0).

## Confidence + critical caveat
- The MT5 stop/gap *mechanism* is **HIGH** (unanimous across MT5-general + comparable venue + MetaTrader5 docs). Its *application to Gate TradFi* is **MEDIUM** — convergent inference (MT5-general + Bybit comparable + Gate-futures-analogous + Gate-TradFi-silence), **not** a Gate-TradFi-primary statement.
- **Gate's general Risk Disclosure is silent** on every gap question and routes to the **User Agreement / per-product TradFi terms (403, unretrieved)**. The only adjacent Gate-official line is a broad liability disclaimer ("not liable for losses… from closing at unfavorable prices or forced liquidation") — consistent with the user-borne / no-NBP picture, but not a description of the fill mechanic.

## Still open → PRE-LIVE verification items (do NOT infer; need the User Agreement or empirical observation)
1. **Gate TradFi User Agreement (403):** does it define any GSLO or max-loss cap the marketing release omits? The one Gate-primary doc that could overturn "no GSLO / unbounded."
2. **`fill_negative` pursuit mechanics** — process, timeline, enforcement of a clawed-back negative balance. Seen only as an API txn type.
3. **Closed-session pricing** — frozen-at-last vs index/synthetic reference (determines whether the 50% stop-out can fire mid-closure or only at reopen, i.e. one-jump gap).
4. **Exact trading-hours window** — cash-core only (9:30–16:00 ET) vs ~24/5 extended (Bybit-analogous). Changes gap frequency/size.

## Design implications (folded into §16 + survival-gate brief)
- **Treat the 50% stop-out as non-guaranteed (gappable).** The survival model must NOT assume the stop holds; the **§16 funding cap is the only hard loss bound** (expected blast radius ≈ the funded ≤8% sleeve; a violent gap adds a negative-balance tail beyond it).
- **Gap-event avoidance is the primary live mitigation, in two layers:** (a) **universal time-based** — reduce/flatten levered exposure before known market closures (weekend/holiday); (b) **name-specific forward gap-sight** — the **`gap-risk-veto-filter`** (§12.2/§12.3: earnings / halt / going-concern / fraud proximity → exclude). This research **re-validates the veto-filter as load-bearing**, not optional.
- **Pre-live gate:** before any real-money cutover, retrieve the Gate TradFi User Agreement (authenticated/browser) to confirm/deny a GSLO + the `fill_negative` mechanics, and confirm closed-session pricing + hours empirically. Paper/challenger phase is unaffected.

## Operator decision 2026-05-29 — C-now / B-pre-live (§16.1)

Folding this finding back through the §13 lexicographic chain (Survive ⊳ Preserve ⊳ Edge ⊳ Return), the operator revisited the §16 option-A acceptance. An unbounded **Survive** tail accepted to keep the CFD vehicle's leverage/universe is the one trade §13 forbids ⟹ A as written is a §13 *relaxation*, not an eyes-open residual. Survive-axis ordering: **B** (defined-risk spreads/LEAPs) is the only structurally compliant option; **C** (flat-before-closure invariant) kills the dominant closure-gap path but leaves a bounded intraday-halt residual; **A** keeps the full tail. Proportioning to the MEDIUM-confidence (analogy-grade) finding + paper-only status + the User-Agreement pre-live gate, the decision is:

- **C now** — the reactive layer is **intraday-flat-by-close**; **flat-before-closure is a hard `survival-gate` invariant** (force-flatten ahead of any closure). The dominant overnight/weekend closure-gap path is *operationally* eliminated (**procedural** — conditional on the flatten reliably firing, **not** structural like B; per **P6** the gate needs a verifiable *am-I-flat* pre-close post-condition + fallback, with the timed flatten action owned by `execution-daemon`); the standing residual is the bounded intraday-halt-reopen case, addressed by the **`gap-risk-veto-filter`** (re-validated load-bearing).
- **B pre-live** — the Gate CFD vehicle is **provisional-for-paper**; **defined-risk instruments (B) are the pre-live target** if the User Agreement confirms no-GSLO/no-cap. The survival model must **not assume the CFD vehicle survives the pre-live gate**.
- Under §13 this is an explicit, **paper-only relaxation** — full compliance is B at the pre-live gate.
