"""FastAPI application exposing the engine to the macOS app over localhost.

Endpoints:
  GET  /health                 liveness + schema version (used by the Docker healthcheck and the app)
  GET  /capabilities           provider/model/vendor surface (Settings UI source of truth)
  GET  /journal[?ticker]       decisions journal parsed from the engine memory log
  GET  /reports[?ticker[&date]] list saved run documents, or return one full document
  GET  /search?q=              live ticker/company search (Yahoo Finance public search)
  GET  /prices?ticker=&days=   recent daily closes for the watchlist sparklines
  GET  /openrouter/models      live OpenRouter model catalog (Settings dropdown)
  POST /test                   model availability check (build client + ping)
  POST /test_fred              FRED API key connectivity check
  POST /runs                   start a run; body = resolved run-config JSON; -> {run_id}
  GET  /runs/{id}/events       SSE stream of the run's events (supports Last-Event-ID resume)
  POST /runs/{id}/cancel       request cancellation (checked between graph nodes)
  GET  /runs/{id}/state        terminal status snapshot

Portfolio Construction Endpoints:
  GET  /portfolio/signals      aggregate analyst signals across all saved reports
  POST /portfolio/construct    run Black-Litterman + mean-variance optimisation
  GET  /portfolio/correlation  return-correlation matrix for a ticker set
  GET  /portfolio/sizing       Kelly-criterion position sizes with correlation penalty
  GET  /portfolio/benchmark    portfolio performance vs SPY / QQQ / DIA
  POST /portfolio/rebalance    compute trade list from current holdings → target weights
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import uuid
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from desk_adapter.protocol import SCHEMA_VERSION
from desk_server.events import sse_format
from desk_server.runner import RunHandle, run_blocking

app = FastAPI(title="TradingDesk engine", version="0.0.1")

# Allow the local Next.js dev server (port 3000) and any production origin
# to reach the API.  Credentials are not sent, so allow_credentials=False is fine.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

_runs: dict[str, RunHandle] = {}

# Runs execute on a dedicated single-worker pool, NOT the event loop's default
# executor. This (a) serializes runs so two concurrent runs never race on the
# shared ``os.environ`` provider keys, and (b) keeps multi-minute runs off the
# default pool that the short /search, /prices, /test endpoints use via
# ``asyncio.to_thread`` — so the UI stays responsive while a run is in flight.
# (A queued run sits at "warming" until the active one finishes.)
_RUN_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="desk-run")

# Evict a finished run from ``_runs`` this long after it completes, so an SSE
# client still has time to drain the tail but the per-run buffer (full report
# markdown + tool output) doesn't accumulate for the container's lifetime.
_RUN_RETENTION_S = 600


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "schema_version": SCHEMA_VERSION, "runs": len(_runs)}


@app.get("/capabilities")
async def capabilities() -> JSONResponse:
    # Imported lazily so /health stays cheap and import errors surface per-call.
    from desk_adapter.introspect import build_capabilities

    return JSONResponse(build_capabilities())


@app.get("/journal")
async def journal(ticker: str | None = None) -> dict:
    """The decisions journal: parsed entries from the engine's memory log.

    Each entry has date, ticker, rating, pending, raw, alpha, holding, decision,
    reflection. Pending entries (raw/alpha None) resolve on a later same-ticker
    run. Powers the app's Ticker Desk journal and watchlist.
    """
    from tradingagents.agents.utils.memory import TradingMemoryLog
    from tradingagents.default_config import DEFAULT_CONFIG

    entries = TradingMemoryLog(DEFAULT_CONFIG).load_entries()
    if ticker:
        entries = [e for e in entries if str(e.get("ticker", "")).upper() == ticker.upper()]
    entries.sort(key=lambda e: e.get("date", ""), reverse=True)
    return {"entries": entries}


@app.get("/reports")
async def reports(ticker: str | None = None, date: str | None = None) -> dict:
    """Saved run documents (the per-run full_states_log JSON).

    With ``ticker`` + ``date``: returns that run's full document (7 report
    sections + bull/bear and 3-way risk transcripts + final decision). With only
    ``ticker`` (or nothing): lists available runs as {ticker, date, rating}.
    """
    import json as _json
    from pathlib import Path

    from tradingagents.agents.utils.rating import parse_rating
    from tradingagents.dataflows.utils import safe_ticker_component
    from tradingagents.default_config import DEFAULT_CONFIG

    results_dir = Path(DEFAULT_CONFIG["results_dir"])

    if ticker and date:
        path = results_dir / safe_ticker_component(ticker) / "TradingAgentsStrategy_logs" / f"full_states_log_{date}.json"
        if not path.exists():
            raise HTTPException(status_code=404, detail="report not found")
        return _json.loads(path.read_text(encoding="utf-8"))

    out = []
    for path in results_dir.glob("*/TradingAgentsStrategy_logs/full_states_log_*.json"):
        folder = path.parent.parent.name
        if ticker and folder.upper() != safe_ticker_component(ticker).upper():
            continue
        run_date = path.stem.replace("full_states_log_", "")
        rating = ""
        with contextlib.suppress(Exception):
            rating = parse_rating(_json.loads(path.read_text(encoding="utf-8")).get("final_trade_decision", ""))
        out.append({"ticker": folder, "date": run_date, "rating": rating})
    out.sort(key=lambda r: r["date"], reverse=True)
    return {"reports": out}


@app.get("/search")
async def search(q: str = "") -> dict:
    """Live ticker/company search via Yahoo Finance's public search endpoint.

    Powers the app's top-bar command search: real symbols + company names, so
    the user can find and add any listed instrument (no key needed). Returns
    ``{results: [{symbol, name, exchange, type}]}`` ordered by Yahoo relevance.
    """
    import json as _json
    import urllib.parse
    import urllib.request

    query = (q or "").strip()
    if not query:
        return {"results": []}

    def _fetch():
        params = urllib.parse.urlencode({"q": query, "quotesCount": 10, "newsCount": 0})
        url = f"https://query2.finance.yahoo.com/v1/finance/search?{params}"
        # Yahoo rejects the default urllib UA; present a browser-like one.
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Macintosh) TradingDesk"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            payload = _json.loads(resp.read())
        out = []
        for quote in payload.get("quotes", []):
            symbol = quote.get("symbol")
            if not symbol:
                continue
            out.append(
                {
                    "symbol": symbol,
                    "name": quote.get("shortname") or quote.get("longname") or quote.get("name") or "",
                    "exchange": quote.get("exchDisp") or quote.get("exchange") or "",
                    "type": quote.get("typeDisp") or quote.get("quoteType") or "",
                }
            )
        return out

    try:
        return {"results": await asyncio.to_thread(_fetch)}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"search failed: {exc}") from exc


@app.get("/prices")
async def prices(ticker: str = "", days: int = 30) -> dict:
    """Recent daily closing prices for a symbol (watchlist sparklines).

    Uses yfinance (already a dependency); returns ``{points: [close, ...]}``
    oldest→newest. Best-effort: an unknown/illiquid symbol just yields an empty
    list (200), so the row simply shows no sparkline. No key needed.
    """
    symbol = (ticker or "").strip()
    if not symbol:
        return {"points": []}

    def _fetch():
        import yfinance as yf

        hist = yf.Ticker(symbol).history(period=f"{max(days, 5)}d")
        return [float(c) for c in hist["Close"].dropna().tolist()]

    try:
        return {"points": await asyncio.to_thread(_fetch)}
    except Exception:  # noqa: BLE001
        return {"points": []}


@app.get("/openrouter/models")
async def openrouter_models() -> dict:
    """Live OpenRouter model catalog (public endpoint, no key needed)."""
    import json as _json
    import urllib.request

    def _fetch():
        req = urllib.request.Request(
            "https://openrouter.ai/api/v1/models", headers={"User-Agent": "TradingDesk"}
        )
        with urllib.request.urlopen(req, timeout=12) as resp:
            payload = _json.loads(resp.read())
        out = []
        for m in payload.get("data", []):
            mid = m.get("id")
            if mid:
                out.append({"label": m.get("name") or mid, "model_id": mid})
        out.sort(key=lambda x: x["model_id"])
        return out

    try:
        return {"models": await asyncio.to_thread(_fetch)}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"could not fetch OpenRouter models: {exc}") from exc


@app.post("/test")
async def test_model(request: Request) -> dict:
    """Quick availability check: build the LLM client and make a tiny call.

    Body: {llm_provider, model, backend_url?, keys?}. Returns {ok} or {ok:false, error}.
    """
    body = await request.json()
    provider = body.get("llm_provider", "")
    model = body.get("model", "")
    base_url = body.get("backend_url")
    keys = {k: v for k, v in (body.get("keys") or {}).items() if v}

    def _ping():
        from tradingagents.llm_clients import create_llm_client

        # Inject the supplied keys only for this check, then restore them — so a
        # /test never leaves a key in the process env for a later run/test.
        saved = {k: os.environ.get(k) for k in keys}
        try:
            os.environ.update(keys)
            client = create_llm_client(provider=provider, model=model, base_url=base_url)
            client.get_llm().invoke("Reply with: OK")
            return True
        finally:
            for k, prior in saved.items():
                if prior is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = prior

    try:
        await asyncio.to_thread(_ping)
        return {"ok": True}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:300]}


@app.post("/test_fred")
async def test_fred(request: Request) -> dict:
    """Validate a FRED API key by making one minimal FRED API call."""
    body = await request.json()
    key = body.get("key", "")

    def _ping():
        import json as _json
        import urllib.parse
        import urllib.request

        query = urllib.parse.urlencode({"series_id": "GDP", "api_key": key, "file_type": "json"})
        url = f"https://api.stlouisfed.org/fred/series?{query}"
        with urllib.request.urlopen(url, timeout=10) as resp:
            _json.loads(resp.read())
        return True

    if not key:
        return {"ok": False, "error": "no key"}
    try:
        await asyncio.to_thread(_ping)
        return {"ok": True}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:200]}


@app.post("/runs")
async def create_run(request: Request) -> dict:
    cfg = await request.json()
    if not cfg.get("ticker") or not cfg.get("trade_date"):
        raise HTTPException(status_code=400, detail="ticker and trade_date are required")
    run_id = uuid.uuid4().hex
    loop = asyncio.get_running_loop()
    handle = RunHandle(run_id, loop)
    _runs[run_id] = handle
    task = loop.run_in_executor(_RUN_EXECUTOR, run_blocking, handle, cfg)
    # Drop the run from _runs a while after it finishes. The done-callback runs
    # on the loop thread, so scheduling call_later from it is thread-safe.
    task.add_done_callback(lambda _t: loop.call_later(_RUN_RETENTION_S, _runs.pop, run_id, None))
    return {"run_id": run_id, "schema_version": SCHEMA_VERSION}


@app.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: str) -> dict:
    handle = _runs.get(run_id)
    if handle is None:
        raise HTTPException(status_code=404, detail="unknown run")
    handle.cancelled = True
    return {"cancelled": True}


@app.get("/runs/{run_id}/state")
async def run_state(run_id: str) -> dict:
    handle = _runs.get(run_id)
    if handle is None:
        raise HTTPException(status_code=404, detail="unknown run")
    return {"run_id": run_id, "status": handle.status, "done": handle.done, "events": handle.seq}


@app.get("/runs/{run_id}/events")
async def run_events(run_id: str, request: Request) -> StreamingResponse:
    handle = _runs.get(run_id)
    if handle is None:
        raise HTTPException(status_code=404, detail="unknown run")

    last = request.headers.get("Last-Event-ID")
    start_idx = int(last) if last and last.isdigit() else 0

    async def gen():
        idx = start_idx
        while True:
            handle.updated.clear()
            while idx < len(handle.events):
                yield sse_format(handle.events[idx])
                idx += 1
            if handle.done and idx >= len(handle.events):
                break
            if await request.is_disconnected():
                break
            try:
                await asyncio.wait_for(handle.updated.wait(), timeout=15)
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


# ─────────────────────────────────────────────────────────────────────────────
# Portfolio Construction Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/portfolio/signals")
async def portfolio_signals() -> dict:
    """Aggregate analyst conviction signals from all saved run reports.

    Returns one signal per ticker (most-recent run). Each entry includes:
    rating, conviction score, expected_return, win_prob, per-analyst verdicts,
    report age_days, and a stale flag (age > 14 days).
    """
    from pathlib import Path
    from dataclasses import asdict
    from tradingagents.default_config import DEFAULT_CONFIG
    from tradingagents.portfolio.signals import aggregate_signals

    results_dir = Path(DEFAULT_CONFIG["results_dir"])

    def _run():
        rows = aggregate_signals(results_dir)
        out = []
        for r in rows:
            d = asdict(r)
            d["analyst_verdicts"] = asdict(r.analyst_verdicts)
            out.append(d)
        return out

    try:
        rows = await asyncio.to_thread(_run)
        return {"signals": rows}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/portfolio/construct")
async def portfolio_construct(request: Request) -> dict:
    """Run Black-Litterman + constrained mean-variance optimisation.

    Body JSON:
      tickers:       list[str]   — symbols to include
      risk_aversion: float       — δ (default 2.5)
      max_position:  float       — per-ticker cap (default 0.40)
      min_position:  float       — per-ticker floor (default 0.02)
      lookback_days: int         — history for covariance (default 90)
    """
    import yfinance as yf
    import pandas as pd
    from pathlib import Path
    from tradingagents.default_config import DEFAULT_CONFIG
    from tradingagents.portfolio.signals import aggregate_signals
    from tradingagents.portfolio.black_litterman import compute_bl_returns
    from tradingagents.portfolio.optimizer import optimize_portfolio

    body = await request.json()
    tickers: list[str] = [t.upper() for t in (body.get("tickers") or [])]
    if not tickers:
        raise HTTPException(status_code=400, detail="tickers list is required")

    risk_aversion: float = float(body.get("risk_aversion", 2.5))
    max_position: float  = float(body.get("max_position", 0.40))
    min_position: float  = float(body.get("min_position", 0.02))
    lookback_days: int   = int(body.get("lookback_days", 90))

    results_dir = Path(DEFAULT_CONFIG["results_dir"])

    def _run():
        # Fetch price history
        raw = yf.download(tickers, period=f"{lookback_days}d", auto_adjust=True, progress=False)
        if isinstance(raw.columns, pd.MultiIndex):
            prices_df = raw["Close"] if "Close" in raw.columns.get_level_values(0) else raw
        else:
            prices_df = raw

        # Load analyst signals
        signal_rows = aggregate_signals(results_dir)

        # Black-Litterman posterior returns
        bl_returns = compute_bl_returns(tickers, prices_df, signal_rows, risk_aversion)

        # Optimise
        result = optimize_portfolio(
            tickers, prices_df, bl_returns, risk_aversion, max_position, min_position
        )
        result["bl_returns"] = bl_returns
        return result

    try:
        result = await asyncio.to_thread(_run)
        return result
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/portfolio/correlation")
async def portfolio_correlation(tickers: str = "", days: int = 90) -> dict:
    """Return pairwise return-correlation matrix.

    Query params:
      tickers: comma-separated ticker list (e.g. AAPL,MSFT,GOOGL)
      days:    look-back window in trading days (default 90)
    """
    from tradingagents.portfolio.correlation import compute_correlation_matrix

    ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    if not ticker_list:
        raise HTTPException(status_code=400, detail="tickers query param is required")

    def _run():
        return compute_correlation_matrix(ticker_list, days=days)

    try:
        return await asyncio.to_thread(_run)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/portfolio/sizing")
async def portfolio_sizing(
    tickers: str = "",
    weights: str = "",
    days: int = 90,
) -> dict:
    """Kelly-criterion position sizes with correlation penalty.

    Query params:
      tickers: comma-separated tickers     (e.g. AAPL,MSFT,GOOGL)
      weights: comma-separated weights     (e.g. 0.4,0.35,0.25) — same order as tickers
      days:    correlation look-back days  (default 90)
    """
    from pathlib import Path
    from tradingagents.default_config import DEFAULT_CONFIG
    from tradingagents.portfolio.signals import aggregate_signals
    from tradingagents.portfolio.correlation import compute_correlation_matrix
    from tradingagents.portfolio.sizing import compute_kelly_sizes

    ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    if not ticker_list:
        raise HTTPException(status_code=400, detail="tickers query param is required")

    weight_vals = [float(w.strip()) for w in weights.split(",") if w.strip()]
    if len(weight_vals) != len(ticker_list):
        # Fall back to equal weights
        weight_vals = [1.0 / len(ticker_list)] * len(ticker_list)
    weight_map = dict(zip(ticker_list, weight_vals))

    results_dir = Path(DEFAULT_CONFIG["results_dir"])

    def _run():
        signal_rows = aggregate_signals(results_dir)
        corr_result = compute_correlation_matrix(ticker_list, days=days)
        positions = compute_kelly_sizes(signal_rows, weight_map, corr_result)
        return {"positions": positions}

    try:
        return await asyncio.to_thread(_run)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/portfolio/benchmark")
async def portfolio_benchmark(
    tickers: str = "",
    weights: str = "",
    days: int = 90,
) -> dict:
    """Portfolio performance vs SPY / QQQ / DIA.

    Query params:
      tickers: comma-separated tickers (e.g. AAPL,MSFT,GOOGL)
      weights: comma-separated weights matching tickers order
      days:    look-back window (default 90)
    """
    from tradingagents.portfolio.benchmark import compute_benchmark_comparison

    ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    if not ticker_list:
        raise HTTPException(status_code=400, detail="tickers query param is required")

    weight_vals = [float(w.strip()) for w in weights.split(",") if w.strip()]
    if len(weight_vals) != len(ticker_list):
        weight_vals = [1.0 / len(ticker_list)] * len(ticker_list)
    weight_map = dict(zip(ticker_list, weight_vals))

    def _run():
        return compute_benchmark_comparison(ticker_list, weight_map, days=days)

    try:
        return await asyncio.to_thread(_run)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/portfolio/rebalance")
async def portfolio_rebalance(request: Request) -> dict:
    """Compute the trade list needed to move from current holdings to target weights.

    Body JSON:
      current_holdings: {ticker: weight}   — current portfolio weights
      target_weights:   {ticker: weight}   — desired portfolio weights
      portfolio_value:  float              — total portfolio $ value (for $ amounts)
    """
    body = await request.json()
    current: dict[str, float] = {k.upper(): float(v) for k, v in (body.get("current_holdings") or {}).items()}
    target:  dict[str, float] = {k.upper(): float(v) for k, v in (body.get("target_weights") or {}).items()}
    portfolio_value: float = float(body.get("portfolio_value", 100_000))

    if not target:
        raise HTTPException(status_code=400, detail="target_weights is required")

    all_tickers = sorted(set(current) | set(target))
    trades = []
    for ticker in all_tickers:
        current_w = current.get(ticker, 0.0)
        target_w  = target.get(ticker, 0.0)
        delta_w   = target_w - current_w
        dollar    = delta_w * portfolio_value

        if abs(delta_w) < 0.001:    # ignore sub-0.1% changes
            continue

        trades.append({
            "ticker":       ticker,
            "action":       "BUY" if delta_w > 0 else "SELL",
            "delta_weight": round(delta_w, 4),
            "dollar_amount": round(abs(dollar), 2),
            "current_weight": round(current_w, 4),
            "target_weight":  round(target_w, 4),
        })

    trades.sort(key=lambda t: -abs(t["delta_weight"]))
    return {"trades": trades, "portfolio_value": portfolio_value}


# ── Options Action ─────────────────────────────────────────────────────────────

def _strike_step(price: float) -> float:
    if price < 25:   return 1.0
    if price < 100:  return 2.5
    if price < 500:  return 5.0
    return 10.0


def _round_strike(price: float, target: float) -> float:
    step = _strike_step(price)
    return max(step, round(target / step) * step)


def _bs_prob_otm(S: float, K: float, T: float, sigma: float) -> float:
    """Risk-neutral probability that the stock finishes above K (for calls)
    using simplified Black-Scholes d2 (risk-free rate assumed 0.05)."""
    import math
    r = 0.05
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return 0.0
    try:
        d2 = (math.log(S / K) + (r - 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
        # Standard normal CDF approximation (Abramowitz & Stegun)
        def _norm_cdf(x: float) -> float:
            a = 0.2316419
            b = [0.319381530, -0.356563782, 1.781477937, -1.821255978, 1.330274429]
            t = 1.0 / (1.0 + a * abs(x))
            poly = sum(b[i] * t ** (i + 1) for i in range(5))
            pdf = math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)
            cdf = 1.0 - pdf * poly
            return cdf if x >= 0 else 1.0 - cdf
        return _norm_cdf(d2)
    except Exception:
        return 0.0


def _generate_trade_ideas(
    ticker: str, price: float, atm_iv: float, rv30: float,
    dte: int, expiry: str, em: float
) -> list[dict]:
    """Return 3 structured trade ideas based on IV regime."""
    iv_rv = atm_iv / rv30 if rv30 > 0 else 1.0
    T = dte / 365

    if iv_rv >= 1.3:
        regime = "high"
    elif iv_rv <= 0.8:
        regime = "low"
    else:
        regime = "normal"

    step = _strike_step(price)

    # Anchor strikes
    atm   = _round_strike(price, price)
    c1    = _round_strike(price, price + em * 0.5)   # +½σ call
    c2    = _round_strike(price, price + em * 1.1)   # +1.1σ call (IC wing)
    c3    = _round_strike(price, price + em * 1.2)   # long wing for IC
    p1    = _round_strike(price, price - em * 0.5)   # −½σ put
    p2    = _round_strike(price, price - em * 1.1)   # −1.1σ put (IC wing)
    p3    = _round_strike(price, price - em * 1.2)   # long wing for IC

    em_pct = em / price
    prob_itm_c1 = _bs_prob_otm(price, c1, T, atm_iv)
    prob_itm_p1 = 1 - _bs_prob_otm(price, p1, T, atm_iv)

    if regime == "high":
        return [
            {
                "strategy": "Iron Condor",
                "direction": "neutral",
                "ivRegime": "High",
                "ivRvRatio": round(iv_rv, 2),
                "expiry": expiry,
                "dte": dte,
                "legs": [
                    f"Sell {int(c2)}C  ·  Buy {int(c3)}C",
                    f"Sell {int(p2)}P  ·  Buy {int(p3)}P",
                ],
                "rationale": (
                    f"IV is {iv_rv:.1f}× realized vol — premium is expensive. "
                    f"Selling both wings beyond the ±{em_pct:.0%} expected move collects "
                    f"credit while keeping risk defined. Theta works for you each day."
                ),
                "probProfit": f"~{int((1 - em_pct * 2.2) * 100)}%",
                "maxProfit": "Net credit received",
                "maxLoss": f"${int(step)} per spread − credit",
            },
            {
                "strategy": "Cash-Secured Put",
                "direction": "bullish",
                "ivRegime": "High",
                "ivRvRatio": round(iv_rv, 2),
                "expiry": expiry,
                "dte": dte,
                "legs": [f"Sell {int(p1)}P"],
                "rationale": (
                    f"Elevated IV inflates put premiums. Selling the {int(p1)}P "
                    f"(~{em_pct/2:.0%} below spot) gets paid to potentially buy {ticker} "
                    f"at a discount. ~{int(prob_itm_p1 * 100)}% chance of assignment."
                ),
                "probProfit": f"~{int((1 - prob_itm_p1) * 100)}%",
                "maxProfit": "Full premium collected",
                "maxLoss": f"${int(p1)} − premium (stock to zero)",
            },
            {
                "strategy": "Covered Call",
                "direction": "neutral / mildly bullish",
                "ivRegime": "High",
                "ivRvRatio": round(iv_rv, 2),
                "expiry": expiry,
                "dte": dte,
                "legs": [f"Own 100 shares  ·  Sell {int(c1)}C"],
                "rationale": (
                    f"Selling the {int(c1)}C (~{em_pct/2:.0%} OTM) generates income "
                    f"against a long position. ~{int((1 - prob_itm_c1) * 100)}% chance "
                    f"the call expires worthless and you keep the full premium."
                ),
                "probProfit": f"~{int((1 - prob_itm_c1) * 100)}%",
                "maxProfit": f"Premium + gains to ${int(c1)}",
                "maxLoss": "Cost basis − premium (stock to zero)",
            },
        ]

    if regime == "low":
        # Debit / vol expansion strategies
        return [
            {
                "strategy": "Bull Call Spread",
                "direction": "bullish",
                "ivRegime": "Low",
                "ivRvRatio": round(iv_rv, 2),
                "expiry": expiry,
                "dte": dte,
                "legs": [f"Buy {int(atm)}C  ·  Sell {int(c1 + step)}C"],
                "rationale": (
                    f"IV is cheap ({iv_rv:.1f}× RV) — buying is efficient. "
                    f"A bull spread captures upside to ${int(c1 + step)} at defined risk. "
                    f"Profits if {ticker} rallies more than {em_pct/2:.0%} by expiry."
                ),
                "probProfit": f"~{int(prob_itm_c1 * 100)}%",
                "maxProfit": f"${int(c1 + step - atm)} − debit paid",
                "maxLoss": "Net debit paid",
            },
            {
                "strategy": "Bear Put Spread",
                "direction": "bearish",
                "ivRegime": "Low",
                "ivRvRatio": round(iv_rv, 2),
                "expiry": expiry,
                "dte": dte,
                "legs": [f"Buy {int(atm)}P  ·  Sell {int(p1 - step)}P"],
                "rationale": (
                    f"Cheap IV makes put spreads cost-effective. "
                    f"Profits if {ticker} falls more than {em_pct/2:.0%}. "
                    f"Defined risk with no exposure beyond the short strike."
                ),
                "probProfit": f"~{int(prob_itm_p1 * 100)}%",
                "maxProfit": f"${int(atm - (p1 - step))} − debit paid",
                "maxLoss": "Net debit paid",
            },
            {
                "strategy": "Long Straddle",
                "direction": "any direction",
                "ivRegime": "Low",
                "ivRvRatio": round(iv_rv, 2),
                "expiry": expiry,
                "dte": dte,
                "legs": [f"Buy {int(atm)}C  ·  Buy {int(atm)}P"],
                "rationale": (
                    f"IV is historically cheap vs realized moves. "
                    f"A straddle profits if {ticker} moves more than ±{em_pct:.0%} "
                    f"(the priced-in expected move). Good before binary catalysts."
                ),
                "probProfit": f"~40% (needs move > ±{em_pct:.0%})",
                "maxProfit": "Unlimited",
                "maxLoss": "Total premium paid",
            },
        ]

    # Normal IV
    return [
        {
            "strategy": "Bull Call Spread",
            "direction": "bullish",
            "ivRegime": "Normal",
            "ivRvRatio": round(iv_rv, 2),
            "expiry": expiry,
            "dte": dte,
            "legs": [f"Buy {int(atm)}C  ·  Sell {int(c1 + step)}C"],
            "rationale": (
                f"Defined-risk bullish position. Profits if {ticker} rises beyond "
                f"${int(atm)} by expiry. IV at normal levels means reasonable pricing."
            ),
            "probProfit": f"~{int(prob_itm_c1 * 100)}%",
            "maxProfit": f"${int(c1 + step - atm)} − debit",
            "maxLoss": "Net debit paid",
        },
        {
            "strategy": "Put Credit Spread",
            "direction": "neutral / bullish",
            "ivRegime": "Normal",
            "ivRvRatio": round(iv_rv, 2),
            "expiry": expiry,
            "dte": dte,
            "legs": [f"Sell {int(p1)}P  ·  Buy {int(p2)}P"],
            "rationale": (
                f"Collect premium by selling downside risk below the expected move. "
                f"~{int((1 - prob_itm_p1) * 100)}% probability the spread expires "
                f"worthless and you keep the full credit."
            ),
            "probProfit": f"~{int((1 - prob_itm_p1) * 100)}%",
            "maxProfit": "Net credit received",
            "maxLoss": f"${int(p1 - p2)} − credit",
        },
        {
            "strategy": "Short Strangle",
            "direction": "neutral",
            "ivRegime": "Normal",
            "ivRvRatio": round(iv_rv, 2),
            "expiry": expiry,
            "dte": dte,
            "legs": [f"Sell {int(c2)}C  ·  Sell {int(p2)}P"],
            "rationale": (
                f"Sell both tails beyond ±{em_pct:.0%} expected move. "
                f"Collects premium on both sides. Add protective wings to cap risk."
            ),
            "probProfit": f"~{int((1 - em_pct * 2) * 100)}%",
            "maxProfit": "Net credit received",
            "maxLoss": "Unlimited without wings — add long strangle for protection",
        },
    ]


def _options_for_ticker(ticker: str) -> dict:
    import math
    from datetime import datetime, date as dt_date
    import numpy as np
    import yfinance as yf

    t = yf.Ticker(ticker.upper())

    # Current price
    hist = t.history(period="5d")
    if hist.empty:
        raise ValueError(f"No price data for {ticker}")
    current_price = float(hist["Close"].iloc[-1])

    # 30-day realized volatility (annualized)
    hist_60 = t.history(period="90d")
    rets = hist_60["Close"].pct_change().dropna()
    rv30 = float(rets.iloc[-22:].std() * math.sqrt(252)) if len(rets) >= 5 else 0.20

    # Available expiries
    expiries = list(t.options or [])
    if not expiries:
        raise ValueError(f"{ticker} has no listed options")

    today = dt_date.today()
    expiry_data = []

    for expiry in expiries[:4]:  # process up to 4 nearest expiries
        try:
            exp_date = datetime.strptime(expiry, "%Y-%m-%d").date()
            dte = max((exp_date - today).days, 1)
            chain = t.option_chain(expiry)
            calls_df = chain.calls.copy()
            puts_df  = chain.puts.copy()

            # Fill NaN numeric cols
            for col in ["volume", "openInterest", "impliedVolatility", "bid", "ask", "lastPrice"]:
                for df in (calls_df, puts_df):
                    if col in df.columns:
                        df[col] = df[col].fillna(0)

            # ATM strike
            atm_idx = (calls_df["strike"] - current_price).abs().idxmin()
            atm_iv  = float(calls_df.loc[atm_idx, "impliedVolatility"])
            if atm_iv <= 0:
                atm_iv = rv30 or 0.20

            em = current_price * atm_iv * math.sqrt(dte / 365)

            # Put/call ratios
            call_vol = float(calls_df["volume"].sum())
            put_vol  = float(puts_df["volume"].sum())
            call_oi  = float(calls_df["openInterest"].sum())
            put_oi   = float(puts_df["openInterest"].sum())
            pcr_vol  = round(put_vol / call_vol, 3) if call_vol > 0 else None
            pcr_oi   = round(put_oi / call_oi, 3)  if call_oi  > 0 else None

            # Unusual activity: volume / OI > 2× or very high raw volume
            unusual = []
            for opt_type, df in [("CALL", calls_df), ("PUT", puts_df)]:
                for _, row in df.iterrows():
                    vol = float(row.get("volume", 0) or 0)
                    oi  = float(row.get("openInterest", 0) or 0)
                    iv  = float(row.get("impliedVolatility", 0) or 0)
                    bid = float(row.get("bid", 0) or 0)
                    ask = float(row.get("ask", 0) or 0)
                    ua  = vol / oi if oi > 0 else 0
                    if (ua >= 2.0 or vol >= 500) and vol > 0:
                        unusual.append({
                            "type": opt_type,
                            "strike": float(row["strike"]),
                            "expiry": expiry,
                            "iv": round(iv, 4),
                            "volume": int(vol),
                            "openInterest": int(oi),
                            "uaRatio": round(ua, 2),
                            "bid": round(bid, 2),
                            "ask": round(ask, 2),
                            "mid": round((bid + ask) / 2, 2),
                        })

            unusual.sort(key=lambda x: -x["volume"])

            # Compact chain (top 10 strikes around ATM for each side)
            atm_strike = float(calls_df.loc[atm_idx, "strike"])
            def _near_atm(df: "pd.DataFrame") -> list[dict]:
                near = df[(df["strike"] >= atm_strike * 0.85) & (df["strike"] <= atm_strike * 1.15)]
                return [
                    {
                        "strike": float(r["strike"]),
                        "bid": round(float(r.get("bid", 0) or 0), 2),
                        "ask": round(float(r.get("ask", 0) or 0), 2),
                        "mid": round((float(r.get("bid", 0) or 0) + float(r.get("ask", 0) or 0)) / 2, 2),
                        "iv": round(float(r.get("impliedVolatility", 0) or 0), 4),
                        "volume": int(float(r.get("volume", 0) or 0)),
                        "oi": int(float(r.get("openInterest", 0) or 0)),
                    }
                    for _, r in near.iterrows()
                ]

            entry = {
                "expiry": expiry,
                "dte": dte,
                "atmIV": round(atm_iv, 4),
                "atmIVPct": f"{atm_iv:.0%}",
                "expectedMove": round(em, 2),
                "expectedMovePct": round(em / current_price, 4),
                "pcrVolume": pcr_vol,
                "pcrOI": pcr_oi,
                "callVolume": int(call_vol),
                "putVolume": int(put_vol),
                "callOI": int(call_oi),
                "putOI": int(put_oi),
                "unusualActivity": unusual[:15],
                "calls": _near_atm(calls_df),
                "puts":  _near_atm(puts_df),
            }

            if not expiry_data:
                # Attach trade ideas only for the nearest expiry
                entry["tradeIdeas"] = _generate_trade_ideas(
                    ticker, current_price, atm_iv, rv30, dte, expiry, em
                )

            expiry_data.append(entry)

        except Exception as exc:  # noqa: BLE001
            expiry_data.append({"expiry": expiry, "error": str(exc)})

    iv_rv_ratio = 0.0
    if expiry_data and "atmIV" in expiry_data[0]:
        iv_rv_ratio = round(expiry_data[0]["atmIV"] / rv30, 2) if rv30 > 0 else 0.0
    if iv_rv_ratio >= 1.3:
        iv_regime = "high"
    elif iv_rv_ratio <= 0.8:
        iv_regime = "low"
    else:
        iv_regime = "normal"

    return {
        "ticker": ticker.upper(),
        "currentPrice": round(current_price, 2),
        "rv30d": round(rv30, 4),
        "rv30dPct": f"{rv30:.0%}",
        "ivRvRatio": iv_rv_ratio,
        "ivRegime": iv_regime,
        "expirations": expiry_data,
    }


@app.get("/options/{ticker}")
async def get_options(ticker: str) -> dict:
    """Options chain, expected move, unusual activity, and AI trade ideas.

    Returns data for up to 4 nearest expiries. Trade ideas are generated for
    the nearest expiry based on IV regime (high / normal / low vs 30-day RV).

    Path params:
      ticker: stock ticker symbol (e.g. AAPL, TSLA, SPY)
    """
    def _run():
        return _options_for_ticker(ticker)

    try:
        return await asyncio.to_thread(_run)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc
