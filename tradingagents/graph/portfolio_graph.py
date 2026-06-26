"""PortfolioGraph — top-level orchestrator for the Portfolio Construction Extension.

Pipeline
--------
1. Screen universe (MomentumQualityScreener)         → top-N candidates
2. Run TradingAgentsGraph.propagate() per candidate  → PortfolioDecisions
3. Filter investable candidates, build portfolio      → PortfolioView
4. [Optional] Rebalance vs current holdings           → RebalanceRecommendation
5. Generate outputs (Excel + Markdown)                → file paths

Usage
-----
    from tradingagents.graph.portfolio_graph import PortfolioGraph
    from tradingagents.default_config import DEFAULT_CONFIG

    config = DEFAULT_CONFIG.copy()
    pg = PortfolioGraph(config=config)

    # First run — no existing holdings
    result = pg.run(trade_date="2026-05-04")

    # Subsequent run with current holdings for rebalancing
    current = {"AAPL": 0.09, "MSFT": 0.08, "NVDA": 0.07, ...}
    result = pg.run(trade_date="2026-05-04", current_holdings=current)

    print(result.portfolio_view)
    print(result.rebalance_recommendation)
    # result.output_paths → {"excel": "...", "markdown": "..."}
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from dotenv import load_dotenv
    load_dotenv()
    load_dotenv(".env.enterprise", override=False)
except ImportError:
    pass

from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.rule import Rule
from rich.text import Text

_console = Console()

from tradingagents.agents.portfolio import (
    MomentumQualityScreener,
    PortfolioView,
    RebalanceRecommendation,
    ScreenerResult,
    create_portfolio_construction_agent,
    create_rebalancing_agent,
)
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.llm_clients import create_llm_client

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class PortfolioRunResult:
    """Container returned by PortfolioGraph.run()."""

    trade_date: str
    screener_results: List[ScreenerResult] = field(default_factory=list)
    ticker_decisions: List[Tuple[str, str, str]] = field(default_factory=list)
    """List of (ticker, final_trade_decision, trader_investment_plan)."""

    portfolio_view: Optional[PortfolioView] = None
    rebalance_recommendation: Optional[RebalanceRecommendation] = None
    output_paths: Dict[str, str] = field(default_factory=dict)
    """{'excel': '/path/to/portfolio.xlsx', 'markdown': '/path/to/memo.md'}"""

    errors: List[str] = field(default_factory=list)
    """Non-fatal errors encountered during the run."""


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------


class PortfolioGraph:
    """Orchestrates screening → per-ticker analysis → construction → rebalancing.

    Parameters
    ----------
    selected_analysts : list of str
        Subset of analysts to run for each ticker.  Default: all four.
    debug : bool
        If True, streams verbose agent output.
    config : dict
        Full TradingAgents config dict.  Must contain a ``portfolio`` sub-key.
        Falls back to ``DEFAULT_CONFIG`` if not provided.
    callbacks : list, optional
        LangChain callback handlers forwarded to each TradingAgentsGraph run.
    """

    def __init__(
        self,
        selected_analysts: Optional[List[str]] = None,
        debug: bool = False,
        config: Optional[Dict[str, Any]] = None,
        callbacks: Optional[List] = None,
    ):
        self.selected_analysts = selected_analysts or [
            "market", "social", "news", "fundamentals"
        ]
        self.debug = debug
        self.config = config or DEFAULT_CONFIG.copy()
        self.callbacks = callbacks or []

        # Ensure portfolio sub-config exists
        if "portfolio" not in self.config:
            self.config["portfolio"] = {}

        portfolio_cfg = self.config["portfolio"]

        # Create output directory for portfolio logs
        self.output_dir = Path(
            portfolio_cfg.get("output_dir") or os.path.join(
                self.config.get("results_dir") or "~/.tradingagents/logs",
                "portfolio",
            )
        ).expanduser()
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Initialise LLM clients (shared across construction + rebalancing agents)
        llm_kwargs = self._get_provider_kwargs()
        if self.callbacks:
            llm_kwargs["callbacks"] = self.callbacks

        deep_client = create_llm_client(
            provider=self.config["llm_provider"],
            model=self.config["deep_think_llm"],
            base_url=self.config.get("backend_url"),
            **llm_kwargs,
        )
        quick_client = create_llm_client(
            provider=self.config["llm_provider"],
            model=self.config["quick_think_llm"],
            base_url=self.config.get("backend_url"),
            **llm_kwargs,
        )
        self.deep_llm = deep_client.get_llm()
        self.quick_llm = quick_client.get_llm()

        # Portfolio-specific agents
        self.screener = MomentumQualityScreener(self.config)
        self.construction_agent = create_portfolio_construction_agent(self.deep_llm)
        self.rebalancing_agent = create_rebalancing_agent(self.quick_llm)

        # Lazy-import TradingAgentsGraph to avoid circular imports
        self._trading_graph_cls = None

    # ------------------------------------------------------------------
    # Provider helpers (mirrors TradingAgentsGraph._get_provider_kwargs)
    # ------------------------------------------------------------------

    def _get_provider_kwargs(self) -> Dict[str, Any]:
        kwargs = {}
        provider = self.config.get("llm_provider", "").lower()
        if provider == "google":
            level = self.config.get("google_thinking_level")
            if level:
                kwargs["thinking_level"] = level
        elif provider in ("openai", "openrouter"):
            effort = self.config.get("openai_reasoning_effort")
            if effort:
                # OpenRouter maps "xhigh" → DeepSeek max reasoning.
                # Native OpenAI uses "medium"/"high"/"low"/"max".
                kwargs["reasoning_effort"] = effort
        elif provider == "anthropic":
            effort = self.config.get("anthropic_effort")
            if effort:
                kwargs["effort"] = effort
        return kwargs

    # ------------------------------------------------------------------
    # TradingAgentsGraph lazy loader
    # ------------------------------------------------------------------

    def _get_trading_graph(self):
        """Return a freshly initialised TradingAgentsGraph instance."""
        if self._trading_graph_cls is None:
            from tradingagents.graph.trading_graph import TradingAgentsGraph
            self._trading_graph_cls = TradingAgentsGraph

        return self._trading_graph_cls(
            selected_analysts=self.selected_analysts,
            debug=self.debug,
            config=self.config,
            callbacks=self.callbacks,
        )

    # ------------------------------------------------------------------
    # Progress display helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _ok(msg: str) -> None:
        """Print a green checkmark milestone."""
        _console.print(f"  [bold green]✓[/bold green] {msg}")

    @staticmethod
    def _fail(msg: str) -> None:
        """Print a red cross milestone."""
        _console.print(f"  [bold red]✗[/bold red] {msg}")

    @staticmethod
    def _step(msg: str) -> None:
        """Print a bold section header."""
        _console.print(f"\n[bold cyan]{msg}[/bold cyan]")

    # ------------------------------------------------------------------
    # Per-ticker analysis
    # ------------------------------------------------------------------

    def _analyze_ticker(
        self,
        ticker: str,
        trade_date: str,
        progress: Optional[Any] = None,
        task_id: Optional[Any] = None,
    ) -> Optional[Tuple[str, str, str, dict]]:
        """Run the full TradingAgentsGraph pipeline for one ticker.

        Returns
        -------
        (ticker, final_trade_decision, trader_investment_plan, full_state)
        or None on failure.
        """
        try:
            logger.info("Analysing %s …", ticker)
            tg = self._get_trading_graph()
            final_state, _ = tg.propagate(ticker, trade_date)
            return (
                ticker,
                final_state.get("final_trade_decision", ""),
                final_state.get("trader_investment_plan", ""),
                dict(final_state),
            )
        except Exception as e:
            logger.error("Error analysing %s: %s", ticker, e)
            return None

    # ------------------------------------------------------------------
    # Main run method
    # ------------------------------------------------------------------

    def run(
        self,
        trade_date: Optional[str] = None,
        current_holdings: Optional[Dict[str, float]] = None,
        rebalance_type: Optional[str] = None,
        tickers_override: Optional[List[str]] = None,
    ) -> PortfolioRunResult:
        """Run the full portfolio construction (and optional rebalancing) pipeline."""
        trade_date = trade_date or str(date.today())
        result = PortfolioRunResult(trade_date=trade_date)

        portfolio_cfg = self.config.get("portfolio", {})
        pre_analysis_cap = portfolio_cfg.get("pre_analysis_cap", 50)
        max_positions = portfolio_cfg.get("max_positions", 30)
        drift_threshold = portfolio_cfg.get("drift_threshold", 0.25)

        _console.print(Rule(f"[bold]TradingAgents Portfolio  ·  {trade_date}[/bold]"))

        # ── Live dashboard ────────────────────────────────────────────────
        from tradingagents.portfolio.dashboard import PortfolioDashboard
        dash = PortfolioDashboard(output_dir=str(self.output_dir), trade_date=trade_date)
        dash.open_browser()
        self._ok(f"Dashboard → [bold]{dash.path}[/bold]")

        # ----------------------------------------------------------------
        # Step 1: Screen / get universe
        # ----------------------------------------------------------------
        universe_tickers = tickers_override or self.screener.get_universe()
        n_universe = len(universe_tickers)

        # Funnel stage 1: screener scores ALL universe tickers quantitatively,
        # then keeps only the top pre_analysis_cap for the expensive LLM step.
        # This prevents 100+ full LLM pipeline runs when a large list is supplied.
        n_to_score = len(universe_tickers)
        n_to_analyse = min(pre_analysis_cap, n_to_score)

        self._step(
            f"Step 1/5  —  Screening universe  "
            f"[dim]({n_universe} input → top {n_to_analyse} for analysis → "
            f"max {max_positions} in portfolio)[/dim]"
        )

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            TimeElapsedColumn(),
            console=_console,
            transient=True,
        ) as prog:
            prog.add_task(
                f"Scoring {n_to_score} tickers on 5-factor model "
                f"(Quality · Growth · Valuation · Momentum · Analyst) …",
                total=None,
            )
            # screen() returns (passed_survivors, hard_filter_failures)
            screener_results, filtered_tickers = self.screener.screen(
                trade_date,
                top_n=n_to_analyse,
                tickers=universe_tickers,
            )

        result.screener_results = screener_results
        candidate_tickers = [sr.ticker for sr in screener_results]
        n_filtered = len(filtered_tickers)

        if n_filtered:
            # Group eliminated tickers by reason for a concise summary
            reason_counts: Dict[str, int] = {}
            for ft in filtered_tickers:
                reason = (ft.filter_reason or "other").split(":")[0].strip()
                reason_counts[reason] = reason_counts.get(reason, 0) + 1
            reason_str = "  |  ".join(f"{cnt} {r}" for r, cnt in reason_counts.items())
            self._ok(
                f"{n_universe} tickers scored  →  "
                f"[yellow]{n_filtered} eliminated by hard filters[/yellow]"
                f"  [dim]({reason_str})[/dim]"
            )
        self._ok(
            f"Top [bold]{len(candidate_tickers)}[/bold] pass to LLM analysis: "
            f"{', '.join(candidate_tickers)}"
        )

        # Push screener data to the dashboard
        dash.update_screener(screener_results, filtered_tickers)
        _console.print(
            f"\n  [dim]Screener chart updated in dashboard →[/dim] "
            f"[bold]{dash.path}[/bold]"
        )

        # ── Pause for user confirmation ───────────────────────────────────
        _console.print(
            f"\n[bold yellow]  ┌─────────────────────────────────────────────────────────┐[/bold yellow]"
            f"\n[bold yellow]  │  Screener complete.                                     │[/bold yellow]"
            f"\n[bold yellow]  │  Review the dashboard, then press Enter to begin        │[/bold yellow]"
            f"\n[bold yellow]  │  the full LLM analysis of the top {len(candidate_tickers):2d} candidates.      │[/bold yellow]"
            f"\n[bold yellow]  └─────────────────────────────────────────────────────────┘[/bold yellow]\n"
        )
        input("  ▶  Press Enter to continue …")
        _console.print()

        # ----------------------------------------------------------------
        # Step 2: Per-ticker analysis  (parallel workers)
        # ----------------------------------------------------------------
        max_workers = portfolio_cfg.get("max_analysis_workers", 3)
        self._step(
            f"Step 2/5  —  Running full agent analysis  "
            f"[dim]({len(candidate_tickers)} tickers  ·  {max_workers} parallel workers)[/dim]"
        )

        ticker_decisions: List[Tuple[str, str, str]] = []
        n = len(candidate_tickers)

        from concurrent.futures import ThreadPoolExecutor, as_completed
        from tradingagents.portfolio.output import generate_ticker_report

        def _analyse_and_report(ticker: str) -> Optional[Tuple[str, str, str, dict, float]]:
            """Worker: run full pipeline + save report. Returns 5-tuple or None."""
            dash.update_ticker_start(ticker, 0, n)
            t0 = time.time()
            res = self._analyze_ticker(ticker, trade_date)
            elapsed = time.time() - t0
            if res is None:
                dash.update_ticker_failed(ticker, elapsed)
                return None
            tkr, final_decision, trader_plan, full_state = res
            report_md = generate_ticker_report(
                ticker=tkr,
                trade_date=trade_date,
                full_state=full_state,
                output_dir=str(self.output_dir),
            )
            # Read the saved markdown so the dashboard can display it inline
            try:
                with open(report_md, encoding="utf-8") as f:
                    md_content = f.read()
            except Exception:
                md_content = ""
            # Extract rating
            rating = "—"
            for line in final_decision.splitlines():
                if line.strip().startswith("**Rating**:"):
                    rating = line.split(":", 1)[-1].strip()
                    break
            dash.update_ticker_done(tkr, rating, elapsed, md_content)
            return tkr, final_decision, trader_plan, full_state, elapsed

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeElapsedColumn(),
            console=_console,
        ) as prog:
            overall = prog.add_task(
                f"Analysing {n} tickers ({max_workers} at a time) …", total=n
            )

            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                future_map = {pool.submit(_analyse_and_report, t): t for t in candidate_tickers}

                for future in as_completed(future_map):
                    orig_ticker = future_map[future]
                    prog.advance(overall)
                    try:
                        res = future.result()
                    except Exception as exc:
                        result.errors.append(f"Analysis failed for {orig_ticker}: {exc}")
                        self._fail(f"{orig_ticker}  — analysis raised exception: {exc}")
                        continue

                    if res is not None:
                        tkr, final_decision, trader_plan, full_state, elapsed = res
                        ticker_decisions.append((tkr, final_decision, trader_plan))
                        rating = "—"
                        for line in final_decision.splitlines():
                            if line.strip().startswith("**Rating**:"):
                                rating = line.split(":", 1)[-1].strip()
                                break
                        _console.print(
                            f"  [bold green]✓[/bold green] {tkr:<6}  "
                            f"[dim]({elapsed:.0f}s)[/dim]  →  [bold]{rating}[/bold]"
                        )
                    else:
                        result.errors.append(f"Analysis failed for {orig_ticker}")
                        self._fail(f"{orig_ticker}  — analysis failed")

        result.ticker_decisions = ticker_decisions

        if not ticker_decisions:
            _console.print("[bold red]No ticker analyses succeeded. Aborting.[/bold red]")
            return result

        # ----------------------------------------------------------------
        # Step 3: Portfolio construction
        # ----------------------------------------------------------------
        self._step("Step 3/5  —  Constructing portfolio")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            TimeElapsedColumn(),
            console=_console,
            transient=True,
        ) as prog:
            prog.add_task(
                f"LLM allocating weights across {len(ticker_decisions)} names …",
                total=None,
            )
            try:
                portfolio_view = self.construction_agent(
                    ticker_decisions, screener_results, self.config
                )
                result.portfolio_view = portfolio_view
            except Exception as e:
                logger.error("Portfolio construction failed: %s", e)
                result.errors.append(f"Construction error: {e}")
                self._fail(f"Construction failed: {e}")
                return result

        total_w = sum(h.target_weight for h in portfolio_view.holdings)
        self._ok(
            f"{len(portfolio_view.holdings)} holdings constructed  "
            f"(total invested: [bold]{total_w:.1%}[/bold])"
        )
        dash.update_portfolio(portfolio_view)

        # Compute pairwise return correlations for portfolio holdings
        try:
            from tradingagents.portfolio.correlation import compute_correlation_matrix
            holding_tickers = [h.ticker for h in portfolio_view.holdings]
            corr_data = compute_correlation_matrix(holding_tickers, trade_date)
            dash.update_correlation(corr_data)
            if corr_data:
                self._ok(
                    f"Correlation matrix computed  "
                    f"({corr_data['n_obs']} trading days  ·  "
                    f"{corr_data['start_date']} → {corr_data['end_date']})"
                )
        except Exception as e:
            logger.warning("Correlation computation failed: %s", e)
        for h in portfolio_view.holdings:
            _console.print(
                f"    [dim]•[/dim] {h.ticker:<6}  {h.target_weight:.1%}  "
                f"[dim]{h.rating}  |  {h.conviction.value} conviction[/dim]"
            )

        # ----------------------------------------------------------------
        # Step 4: Rebalancing (optional)
        # ----------------------------------------------------------------
        if current_holdings is not None:
            resolved_rebalance_type = rebalance_type or (
                "initial_construction" if not current_holdings else "monthly_scheduled"
            )
            self._step(f"Step 4/5  —  Rebalancing ({resolved_rebalance_type})")

            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                TimeElapsedColumn(),
                console=_console,
                transient=True,
            ) as prog:
                prog.add_task("Computing trades + generating rationale …", total=None)
                try:
                    rec = self.rebalancing_agent(
                        portfolio_view=portfolio_view,
                        current_holdings=current_holdings,
                        trade_date=trade_date,
                        rebalance_type=resolved_rebalance_type,
                        drift_threshold=drift_threshold,
                    )
                    result.rebalance_recommendation = rec
                except Exception as e:
                    logger.error("Rebalancing failed: %s", e)
                    result.errors.append(f"Rebalancing error: {e}")
                    self._fail(f"Rebalancing failed: {e}")

            if result.rebalance_recommendation:
                dash.update_rebalance(rec)
                active = [t for t in rec.trades if t.action.value != "Hold"]
                self._ok(
                    f"{len(active)} rebalance trades  "
                    f"(estimated turnover: [bold]{rec.portfolio_turnover_pct:.1%}[/bold])"
                )
                for t in active:
                    colour = "green" if t.action.value == "Buy" else "red" if t.action.value == "Sell" else "yellow"
                    _console.print(
                        f"    [dim]•[/dim] {t.ticker:<6}  "
                        f"[bold {colour}]{t.action.value:<4}[/bold {colour}]  "
                        f"{t.current_weight:.1%} → {t.target_weight:.1%}  "
                        f"[dim]{t.priority} priority[/dim]"
                    )
        else:
            self._step("Step 4/5  —  Rebalancing")
            _console.print("  [dim]Skipped (no current_holdings provided)[/dim]")

        # ----------------------------------------------------------------
        # Step 5: Generate outputs
        # ----------------------------------------------------------------
        self._step("Step 5/5  —  Writing outputs")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            TimeElapsedColumn(),
            console=_console,
            transient=True,
        ) as prog:
            prog.add_task("Generating Excel workbook + Markdown memo …", total=None)
            try:
                from tradingagents.portfolio.output import generate_outputs
                # Pass all screener results (passed + filtered) so the Excel
                # screener sheet shows the full scored universe for reference.
                all_screener_results = screener_results + filtered_tickers
                paths = generate_outputs(
                    portfolio_view=portfolio_view,
                    rebalance_rec=result.rebalance_recommendation,
                    screener_results=all_screener_results,
                    trade_date=trade_date,
                    output_dir=str(self.output_dir),
                )
                result.output_paths = paths
            except Exception as e:
                logger.error("Output generation failed: %s", e)
                result.errors.append(f"Output error: {e}")
                self._fail(f"Output generation failed: {e}")

        if result.output_paths:
            self._ok(f"Excel  →  [bold]{result.output_paths.get('excel', '')}[/bold]")
            self._ok(f"Memo   →  [bold]{result.output_paths.get('markdown', '')}[/bold]")

        if result.errors:
            _console.print(f"\n[yellow]Non-fatal errors:[/yellow] {result.errors}")

        dash.finalize()
        self._ok(f"Dashboard (final) →  [bold]{dash.path}[/bold]")
        _console.print(Rule("[bold green]Portfolio run complete[/bold green]"))
        return result

    # ------------------------------------------------------------------
    # Convenience: drift monitor
    # ------------------------------------------------------------------

    def check_drift(
        self,
        portfolio_view: PortfolioView,
        current_holdings: Dict[str, float],
        trade_date: Optional[str] = None,
    ) -> RebalanceRecommendation:
        """Check current holdings against a target portfolio for drift triggers.

        Use this between monthly runs to catch positions that have drifted
        beyond the configured ``drift_threshold`` due to price moves.

        Parameters
        ----------
        portfolio_view : PortfolioView
            The most recently constructed target portfolio.
        current_holdings : dict[ticker → weight]
            Current live weights (e.g. refreshed from a brokerage API).
        trade_date : str, optional
            Defaults to today.

        Returns
        -------
        RebalanceRecommendation  (rebalance_type="drift_triggered")
        """
        drift_threshold = self.config.get("portfolio", {}).get("drift_threshold", 0.25)
        td = trade_date or str(date.today())
        return self.rebalancing_agent(
            portfolio_view=portfolio_view,
            current_holdings=current_holdings,
            trade_date=td,
            rebalance_type="drift_triggered",
            drift_threshold=drift_threshold,
        )
