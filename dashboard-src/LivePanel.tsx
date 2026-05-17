import { useEffect, useMemo, useState } from "react";

type DayBar = { c: number; h: number; l: number; o: number; v: number };
type Min = { c: number; h: number; l: number; o: number; v: number; t: number };
type SnapshotTicker = {
  day?: DayBar;
  lastTrade?: { p: number; t: number; c?: number[] };
  prevDay?: DayBar;
  min?: Min;
  todaysChange?: number;
  todaysChangePerc?: number;
  updated?: number;
};
type QuoteResp = {
  ticker: string;
  snapshot?: { ticker?: SnapshotTicker };
  minutes?: { results?: Min[] };
  fetched_at: string;
};
type Contract = {
  details?: { contract_type?: "call" | "put"; strike_price?: number; expiration_date?: string };
  greeks?: { delta?: number; gamma?: number; theta?: number; vega?: number };
  implied_volatility?: number;
  open_interest?: number;
  day?: { volume?: number; close?: number };
};
type OptionsResp = {
  ticker: string;
  snapshot?: { results?: Contract[] };
  fetched_at: string;
};

type Session = "PRE" | "REG" | "AFTER" | "CLOSED";

const fmtUSD = (n: number) =>
  n.toLocaleString(undefined, { style: "currency", currency: "USD", minimumFractionDigits: 2 });
const fmtPct = (n: number) => `${(n * 100).toFixed(2)}%`;
const fmtInt = (n: number) => n.toLocaleString();
const signed = (n: number) => (n >= 0 ? "+" : "") + n.toFixed(2);

// Determine the US/Eastern session for a given epoch-ms timestamp.
// Pre 04:00–09:30 ET, Reg 09:30–16:00 ET, After 16:00–20:00 ET. Weekends → CLOSED.
const sessionFor = (ms: number): Session => {
  const d = new Date(ms);
  const et = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York",
    weekday: "short",
    hour: "numeric",
    minute: "numeric",
    hour12: false,
  }).formatToParts(d);
  const wk = et.find((p) => p.type === "weekday")?.value ?? "";
  const hh = parseInt(et.find((p) => p.type === "hour")?.value ?? "0", 10);
  const mm = parseInt(et.find((p) => p.type === "minute")?.value ?? "0", 10);
  if (wk === "Sat" || wk === "Sun") return "CLOSED";
  const min = hh * 60 + mm;
  if (min >= 4 * 60 && min < 9 * 60 + 30) return "PRE";
  if (min >= 9 * 60 + 30 && min < 16 * 60) return "REG";
  if (min >= 16 * 60 && min < 20 * 60) return "AFTER";
  return "CLOSED";
};

const SESSION_LABEL: Record<Session, string> = {
  PRE: "Pre-market",
  REG: "Regular session",
  AFTER: "After-hours",
  CLOSED: "Market closed",
};

const Sparkline = ({ bars, prevClose }: { bars: Min[]; prevClose?: number }) => {
  if (bars.length < 2) return null;
  const closes = bars.map((b) => b.c);
  const ys = prevClose != null ? [...closes, prevClose] : closes;
  const min = Math.min(...ys);
  const max = Math.max(...ys);
  const range = max - min || 1;
  const w = 280;
  const h = 60;
  const step = w / (closes.length - 1);
  const pts = closes
    .map((c, i) => `${(i * step).toFixed(1)},${(h - ((c - min) / range) * h).toFixed(1)}`)
    .join(" ");
  const up = closes[closes.length - 1] >= (prevClose ?? closes[0]);
  const color = up ? "#16a34a" : "#dc2626";
  const refY = prevClose != null ? h - ((prevClose - min) / range) * h : null;
  return (
    <svg width={w} height={h} className="sparkline" viewBox={`0 0 ${w} ${h}`}>
      {refY != null && (
        <line x1={0} x2={w} y1={refY} y2={refY} stroke="currentColor" strokeOpacity="0.25" strokeDasharray="3 3" />
      )}
      <polyline points={pts} fill="none" stroke={color} strokeWidth="1.5" />
    </svg>
  );
};

const summarizeOptions = (contracts: Contract[]) => {
  let calls = 0;
  let puts = 0;
  let callOI = 0;
  let putOI = 0;
  let callVol = 0;
  let putVol = 0;
  let ivSum = 0;
  let ivN = 0;
  for (const c of contracts) {
    const t = c.details?.contract_type;
    if (t === "call") {
      calls++;
      callOI += c.open_interest ?? 0;
      callVol += c.day?.volume ?? 0;
    } else if (t === "put") {
      puts++;
      putOI += c.open_interest ?? 0;
      putVol += c.day?.volume ?? 0;
    }
    if (typeof c.implied_volatility === "number" && c.implied_volatility > 0) {
      ivSum += c.implied_volatility;
      ivN++;
    }
  }
  return {
    contractCount: contracts.length,
    callCount: calls,
    putCount: puts,
    callOI,
    putOI,
    callVol,
    putVol,
    pcRatio: callVol > 0 ? putVol / callVol : null,
    pcOiRatio: callOI > 0 ? putOI / callOI : null,
    avgIV: ivN > 0 ? ivSum / ivN : null,
  };
};

// Polygon timestamps are sometimes nanoseconds (lastTrade.t / updated),
// sometimes milliseconds (min.t / bar.t). Normalize to ms.
const toMs = (t: number): number => (t > 1e14 ? Math.floor(t / 1e6) : t);

// Slice 1-min bars to "the latest trading day" — last bar's ET date.
const filterToLatestSessionDay = (bars: Min[]): Min[] => {
  if (bars.length === 0) return bars;
  const lastMs = toMs(bars[bars.length - 1].t);
  const lastDay = new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/New_York",
    year: "numeric", month: "2-digit", day: "2-digit",
  }).format(new Date(lastMs));
  return bars.filter((b) => {
    const d = new Intl.DateTimeFormat("en-CA", {
      timeZone: "America/New_York",
      year: "numeric", month: "2-digit", day: "2-digit",
    }).format(new Date(toMs(b.t)));
    return d === lastDay;
  });
};

export const LivePanel = ({ ticker }: { ticker: string }) => {
  const [quote, setQuote] = useState<QuoteResp | null>(null);
  const [options, setOptions] = useState<OptionsResp | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshCount, setRefreshCount] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setErr(null);
    setQuote(null);
    setOptions(null);
    Promise.all([
      fetch(`/__api/polygon/quote?ticker=${ticker}`).then((r) => r.json()),
      fetch(`/__api/polygon/options?ticker=${ticker}`).then((r) => r.json()),
    ])
      .then(([q, o]) => {
        if (cancelled) return;
        setQuote(q);
        setOptions(o);
      })
      .catch((e) => !cancelled && setErr(String(e)))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [ticker, refreshCount]);

  const view = useMemo(() => {
    const snap = quote?.snapshot?.ticker;
    if (!snap) return null;
    const last = snap.lastTrade?.p ?? snap.min?.c ?? snap.day?.c ?? null;
    const prev = snap.prevDay?.c ?? null;
    const dayChange = snap.todaysChange ?? (last != null && prev != null ? last - prev : null);
    const dayChangePct =
      snap.todaysChangePerc != null
        ? snap.todaysChangePerc / 100
        : (dayChange != null && prev ? dayChange / prev : null);

    const updatedMs = snap.updated ? toMs(snap.updated) : Date.now();
    const lastTradeMs = snap.lastTrade?.t ? toMs(snap.lastTrade.t) : updatedMs;
    const session = sessionFor(lastTradeMs);

    const rawBars = quote?.minutes?.results ?? [];
    const todaysBars = filterToLatestSessionDay(rawBars);

    return { snap, last, prev, dayChange, dayChangePct, session, lastTradeMs, bars: todaysBars };
  }, [quote]);

  if (loading) return <div className="live live-loading">Loading live data for {ticker}…</div>;
  if (err) return <div className="live live-err">Polygon error: {err}</div>;
  if (!view) return <div className="live live-warn">Polygon returned no snapshot for {ticker}.</div>;

  const { snap, last, prev, dayChange, dayChangePct, session, lastTradeMs, bars } = view;
  const isExtended = session === "PRE" || session === "AFTER";
  const contracts = options?.snapshot?.results ?? [];
  const opt = summarizeOptions(contracts);

  return (
    <div className="live">
      <div className="live-row">
        <div className="live-tile live-price">
          <div className="live-tile-label">
            Last <span className={`session-tag s-${session}`}>{session}</span>
          </div>
          <div className="live-price-row">
            <span className="live-price-val">{last != null ? fmtUSD(last) : "—"}</span>
            {dayChange != null && dayChangePct != null && (
              <span className={`live-change ${dayChange >= 0 ? "up" : "down"}`}>
                {dayChange >= 0 ? "▲" : "▼"} {fmtUSD(Math.abs(dayChange))} ({fmtPct(Math.abs(dayChangePct))})
              </span>
            )}
          </div>
          <div className="live-meta">
            {snap.day && (
              <>
                <span>O {fmtUSD(snap.day.o || snap.prevDay?.c || 0)}</span>
                <span>H {fmtUSD(snap.day.h)}</span>
                <span>L {fmtUSD(snap.day.l)}</span>
                <span>V {fmtInt(snap.day.v)}</span>
              </>
            )}
            {prev != null && <span>Prev {fmtUSD(prev)}</span>}
            <span title={new Date(lastTradeMs).toLocaleString()}>
              {SESSION_LABEL[session]}
            </span>
          </div>
        </div>

        {isExtended && last != null && prev != null && (
          <div className="live-tile live-ext">
            <div className="live-tile-label">
              {session === "PRE" ? "Pre-market vs prev close" : "After-hours vs prev close"}
            </div>
            <div className="live-price-row">
              <span className="live-price-val">{fmtUSD(last)}</span>
              <span className={`live-change ${last - prev >= 0 ? "up" : "down"}`}>
                {last - prev >= 0 ? "▲" : "▼"} {fmtUSD(Math.abs(last - prev))} ({fmtPct(Math.abs((last - prev) / prev))})
              </span>
            </div>
            <div className="live-meta">
              <span>Δ ${signed(last - prev)} from {fmtUSD(prev)}</span>
            </div>
          </div>
        )}

        <div className="live-tile live-spark">
          <div className="live-tile-label">1d intraday ({bars.length} min bars)</div>
          <Sparkline bars={bars} prevClose={prev ?? undefined} />
        </div>

        <div className="live-tile">
          <div className="live-tile-label">Options snapshot</div>
          {opt.contractCount > 0 ? (
            <table className="live-opt">
              <tbody>
                <tr>
                  <td>Contracts</td>
                  <td>{fmtInt(opt.contractCount)} ({fmtInt(opt.callCount)}C / {fmtInt(opt.putCount)}P)</td>
                </tr>
                <tr>
                  <td>P/C OI</td>
                  <td>{opt.pcOiRatio != null ? opt.pcOiRatio.toFixed(2) : "—"}</td>
                </tr>
                <tr>
                  <td>P/C Vol</td>
                  <td>{opt.pcRatio != null ? opt.pcRatio.toFixed(2) : "—"}</td>
                </tr>
                <tr>
                  <td>Avg IV</td>
                  <td>{opt.avgIV != null ? fmtPct(opt.avgIV) : "—"}</td>
                </tr>
              </tbody>
            </table>
          ) : (
            <div className="muted">no data</div>
          )}
        </div>

        <div className="live-actions">
          <button
            className="icon-btn"
            onClick={() => setRefreshCount((n) => n + 1)}
            title="refresh"
            aria-label="refresh"
          >
            ↻
          </button>
        </div>
      </div>
    </div>
  );
};
