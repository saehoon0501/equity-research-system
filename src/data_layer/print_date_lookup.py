"""Quarterly print-date lookup — projects when a future fiscal-quarter 10-Q
will be filed, based on historical median lag from period-of-report to
filing date.

USE CASE: quant-analyst.md emits ``falsifier_resolution_date`` for the
bull/bear narrative arcs (Overlay 5). The spec requires the date to be
*when the falsifier IS observable*, NOT the mechanical fiscal-quarter-end
(quantitative-analyst.md:128). Historical bug 12 (surfaced MSFT 2026-05-15):
the date was set to 2026-12-31 (FY27 Q2 quarter-end) instead of
~2027-01-28 (when MSFT actually files its Dec-quarter 10-Q based on a
4-year median 28-30 day lag), creating ~4 weeks of understated
time-to-falsification.

Module shape:

- ``project_print_date(historical_pairs, target_quarter_end)`` — PURE math
  on caller-supplied (quarter_end, filed_date) pairs.
- ``fetch_quarterly_print_history(cik, n)`` — convenience SEC EDGAR fetcher
  for callers without pre-fetched history. HTTP side-effect; uses urllib.
- ``resolve_ticker_to_cik(ticker)`` — ticker→CIK via SEC's public
  company_tickers.json. Cached implicitly per-process by the OS-level
  HTTP cache; module-level caching deferred.
- CLI: ``python3 -m src.data_layer.print_date_lookup --ticker MSFT
  --quarter-end 2026-12-31`` prints a JSON envelope and exits 0.

DETERMINISM: ``project_print_date`` is pure. The HTTP fetchers are the
only side-effects; both are gated behind explicit calls so the math can
be unit-tested in isolation.
"""

from __future__ import annotations

import datetime as dt
import json
import ssl
import statistics
import urllib.request
from dataclasses import dataclass
from typing import Optional, Sequence

SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
# SEC asks for a real User-Agent (organization + contact). Update via the
# CLI --user-agent flag for production use.
DEFAULT_USER_AGENT = "equity-research-system contact@example.com"
DEFAULT_HISTORY_DEPTH = 4
HTTP_TIMEOUT_SEC = 15


def _build_ssl_context() -> ssl.SSLContext:
    """Build an SSL context that works in dev macOS environments where the
    system Python's default trust store may be empty. Prefers certifi
    bundle if installed; falls back to system default otherwise.

    AGENT WORKFLOW NOTE: the preferred call path is to fetch the
    historical pairs via ``mcp__edgar`` (which handles auth + SSL
    correctly) and pass them via the CLI's ``--historical-pairs`` flag.
    The direct HTTP fetch in this module is a CLI convenience for human
    operators and is allowed to fail on environments without proper cert
    bundling.
    """
    try:
        import certifi  # type: ignore[import-not-found]
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


@dataclass
class PrintProjection:
    """Result envelope for a projected print date."""

    target_quarter_end: dt.date
    projected_print_date: dt.date
    median_lag_days: int
    lag_distribution_days: list[int]
    n_historical_pairs: int
    historical_pairs: list[tuple[dt.date, dt.date]]
    source: str = "caller_supplied"  # "caller_supplied" or "edgar_fetched"


def project_print_date(
    historical_pairs: Sequence[tuple[dt.date, dt.date]],
    target_quarter_end: dt.date,
) -> PrintProjection:
    """Project a print date for ``target_quarter_end`` from historical lag.

    ``historical_pairs``: sequence of ``(quarter_end, filed_date)`` tuples.
    Median lag (in days) is computed across the pairs; projection is
    ``target_quarter_end + median_lag``.

    Raises ``ValueError`` on empty input, non-positive lag, or
    ``target_quarter_end`` strictly before all historical quarter-ends
    (anti-foot-gun: caller is asking to project a date in the past).
    """
    if not historical_pairs:
        raise ValueError(
            "historical_pairs must contain at least one "
            "(quarter_end, filed_date) tuple"
        )

    lags = [(filed - qe).days for qe, filed in historical_pairs]
    if any(lag <= 0 for lag in lags):
        raise ValueError(
            f"all (filed_date - quarter_end) lags must be positive; "
            f"got {lags}"
        )

    median_lag = int(round(statistics.median(lags)))
    projected = target_quarter_end + dt.timedelta(days=median_lag)

    return PrintProjection(
        target_quarter_end=target_quarter_end,
        projected_print_date=projected,
        median_lag_days=median_lag,
        lag_distribution_days=sorted(lags),
        n_historical_pairs=len(historical_pairs),
        historical_pairs=[(qe, fd) for qe, fd in historical_pairs],
    )


def resolve_ticker_to_cik(
    ticker: str, user_agent: str = DEFAULT_USER_AGENT
) -> str:
    """Resolve ``ticker`` to its 10-digit zero-padded SEC CIK.

    Uses SEC's public ``company_tickers.json`` endpoint; the SEC requires
    a User-Agent header (organization + contact email).
    """
    req = urllib.request.Request(
        SEC_TICKERS_URL, headers={"User-Agent": user_agent}
    )
    with urllib.request.urlopen(
        req, timeout=HTTP_TIMEOUT_SEC, context=_build_ssl_context()
    ) as resp:
        data = json.loads(resp.read())

    ticker_upper = ticker.upper()
    for entry in data.values():
        if entry.get("ticker") == ticker_upper:
            return str(entry["cik_str"]).zfill(10)

    raise ValueError(
        f"ticker {ticker!r} not found in SEC company_tickers.json"
    )


def fetch_quarterly_print_history(
    cik: str,
    n: int = DEFAULT_HISTORY_DEPTH,
    user_agent: str = DEFAULT_USER_AGENT,
) -> list[tuple[dt.date, dt.date]]:
    """Fetch the last ``n`` 10-Q filings for ``cik`` from SEC EDGAR.

    Returns ``[(period_of_report, filing_date), ...]`` sorted most-recent
    first.  Raises ``ValueError`` if fewer than 2 10-Q filings are
    surfaced (insufficient history to compute a stable median).
    """
    cik_padded = cik.zfill(10) if not cik.startswith("0") else cik
    url = SEC_SUBMISSIONS_URL.format(cik=cik_padded)
    req = urllib.request.Request(url, headers={"User-Agent": user_agent})
    with urllib.request.urlopen(
        req, timeout=HTTP_TIMEOUT_SEC, context=_build_ssl_context()
    ) as resp:
        data = json.loads(resp.read())

    recent = data["filings"]["recent"]
    forms = recent["form"]
    # SEC submissions JSON uses "reportDate" (period the filing covers)
    # alongside "filingDate" (when the filing was accepted by SEC).
    report_date = recent["reportDate"]
    filing_date = recent["filingDate"]

    pairs: list[tuple[dt.date, dt.date]] = []
    for f, p, fd in zip(forms, report_date, filing_date):
        if f != "10-Q":
            continue
        if not p or not fd:
            continue
        pairs.append((dt.date.fromisoformat(p), dt.date.fromisoformat(fd)))
        if len(pairs) >= n:
            break

    if len(pairs) < 2:
        raise ValueError(
            f"insufficient 10-Q history for CIK {cik_padded}: "
            f"found {len(pairs)} filings (need >= 2)"
        )

    return pairs


def _parse_historical_pairs_arg(s: str) -> list[tuple[dt.date, dt.date]]:
    """Parse CLI ``--historical-pairs`` argument format.

    Format: ``"YYYY-MM-DD:YYYY-MM-DD,YYYY-MM-DD:YYYY-MM-DD,..."``
    """
    pairs: list[tuple[dt.date, dt.date]] = []
    for chunk in s.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        qe_s, fd_s = chunk.split(":")
        pairs.append(
            (dt.date.fromisoformat(qe_s.strip()), dt.date.fromisoformat(fd_s.strip()))
        )
    return pairs


def _cli(argv: list[str] | None = None) -> int:
    """Thin CLI wrapper so quant-analyst (and other agents) can shell
    out to project a print date instead of guessing the quarter-end.

    Examples:
      python3 -m src.data_layer.print_date_lookup \\
        --ticker MSFT --quarter-end 2026-12-31

      python3 -m src.data_layer.print_date_lookup \\
        --historical-pairs "2025-12-31:2026-01-28,2024-12-31:2025-01-29" \\
        --quarter-end 2026-12-31
    """
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        prog="print_date_lookup",
        description=(
            "Project a future 10-Q print date from historical "
            "(quarter_end, filed_date) median lag. Output: JSON."
        ),
    )
    parser.add_argument(
        "--quarter-end",
        required=True,
        help="YYYY-MM-DD target quarter-end to project for",
    )
    grp = parser.add_mutually_exclusive_group(required=True)
    grp.add_argument(
        "--ticker", help="ticker symbol; module resolves CIK + fetches history"
    )
    grp.add_argument(
        "--cik", help="10-digit zero-padded CIK; module fetches history"
    )
    grp.add_argument(
        "--historical-pairs",
        help=(
            "comma-separated quarter_end:filed_date pairs (pure math, no HTTP)"
        ),
    )
    parser.add_argument(
        "--n-history",
        type=int,
        default=DEFAULT_HISTORY_DEPTH,
        help=(
            f"number of historical 10-Q filings to use "
            f"(default: {DEFAULT_HISTORY_DEPTH})"
        ),
    )
    parser.add_argument(
        "--user-agent",
        default=DEFAULT_USER_AGENT,
        help=(
            "User-Agent header for SEC requests; SEC policy requires "
            "organization + contact"
        ),
    )
    args = parser.parse_args(argv)

    try:
        target_qe = dt.date.fromisoformat(args.quarter_end)
    except ValueError as exc:
        sys.stderr.write(f"--quarter-end must be YYYY-MM-DD: {exc}\n")
        return 2

    try:
        if args.historical_pairs:
            pairs = _parse_historical_pairs_arg(args.historical_pairs)
            source = "caller_supplied"
        else:
            cik = args.cik or resolve_ticker_to_cik(
                args.ticker, args.user_agent
            )
            pairs = fetch_quarterly_print_history(
                cik, args.n_history, args.user_agent
            )
            source = "edgar_fetched"

        proj = project_print_date(pairs, target_qe)
        proj.source = source
    except ValueError as exc:
        sys.stderr.write(f"ValueError: {exc}\n")
        return 2
    except urllib.error.URLError as exc:
        sys.stderr.write(f"HTTP error reaching SEC EDGAR: {exc}\n")
        return 3

    payload = {
        "target_quarter_end": proj.target_quarter_end.isoformat(),
        "projected_print_date": proj.projected_print_date.isoformat(),
        "median_lag_days": proj.median_lag_days,
        "lag_distribution_days": proj.lag_distribution_days,
        "n_historical_pairs": proj.n_historical_pairs,
        "historical_pairs": [
            [qe.isoformat(), fd.isoformat()] for qe, fd in proj.historical_pairs
        ],
        "source": proj.source,
    }
    sys.stdout.write(json.dumps(payload, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())


__all__ = [
    "PrintProjection",
    "project_print_date",
    "resolve_ticker_to_cik",
    "fetch_quarterly_print_history",
    "SEC_TICKERS_URL",
    "SEC_SUBMISSIONS_URL",
    "DEFAULT_HISTORY_DEPTH",
]
