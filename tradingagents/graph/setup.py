# TradingAgents/graph/setup.py

from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from tradingagents.agents import (
    create_aggressive_debator,
    create_bear_researcher,
    create_bull_researcher,
    create_conservative_debator,
    create_fundamentals_analyst,
    create_market_analyst,
    create_market_technician,
    create_msg_delete,
    create_neutral_debator,
    create_news_analyst,
    create_portfolio_manager,
    create_research_manager,
    create_sentiment_analyst,
    create_trader,
)
from tradingagents.agents.analysts.quantitative_analyst import create_quantitative_analyst
from tradingagents.agents.analysts.valuation_analyst import create_valuation_analyst
from tradingagents.agents.utils.agent_states import AgentState

from .analyst_execution import build_analyst_execution_plan
from .conditional_logic import ConditionalLogic
from .parallel_analysts import create_parallel_analysts_node

# Every target a shared conditional router can return. Each edge driven by the
# router maps all of them, so a fall-through return (e.g. under prompt/i18n/
# refactor drift in the speaker labels) can never hit a missing path_map entry
# and crash LangGraph mid-run (#1088).
DEBATE_PATH_MAP = {
    "Bull Researcher": "Bull Researcher",
    "Bear Researcher": "Bear Researcher",
    "Research Manager": "Research Manager",
}
RISK_ANALYSIS_PATH_MAP = {
    "Aggressive Analyst": "Aggressive Analyst",
    "Conservative Analyst": "Conservative Analyst",
    "Neutral Analyst": "Neutral Analyst",
    "Portfolio Manager": "Portfolio Manager",
}


class GraphSetup:
    """Handles the setup and configuration of the agent graph."""

    def __init__(
        self,
        quick_thinking_llm: Any,
        deep_thinking_llm: Any,
        debate_llm: Any,
        tool_nodes: dict[str, ToolNode],
        conditional_logic: ConditionalLogic,
    ):
        """Initialize with required components.

        Args:
            quick_thinking_llm: Fast model for analyst data-gathering nodes and trader.
            deep_thinking_llm:  Strong model for Research Manager and Portfolio Manager.
            debate_llm:         Fast model for the 5 adversarial debate nodes
                                (Bull, Bear, Aggressive, Conservative, Neutral).
                                Falls back to quick_thinking_llm when no dedicated
                                debate provider is configured.
            tool_nodes:         ToolNode instances keyed by analyst type.
            conditional_logic:  Routing logic for debate/risk-discussion rounds.
        """
        self.quick_thinking_llm = quick_thinking_llm
        self.deep_thinking_llm = deep_thinking_llm
        self.debate_llm = debate_llm
        self.tool_nodes = tool_nodes
        self.conditional_logic = conditional_logic

    def setup_graph(
        self,
        selected_analysts=("market", "social", "news", "fundamentals"),
        debate_mode: str = "5",
        parallel_analysts: bool = True,
    ):
        """Set up and compile the agent workflow graph.

        Args:
            selected_analysts (list): List of analyst types to include. Options are:
                - "market": Market analyst
                - "social": Social media analyst
                - "news": News analyst
                - "fundamentals": Fundamentals analyst
            debate_mode (str): "5" for the full 5-advocate risk debate
                (Aggressive → Conservative → Neutral), or "3" to use only the
                Neutral Analyst as the single risk reviewer (faster, lower cost).
            parallel_analysts (bool): When True (default), all selected analysts
                run concurrently in threads — ~3× faster.  Set to False for
                providers with strict per-key RPM limits (NVIDIA NIM free tier,
                OpenRouter free models, local Ollama) where simultaneous calls
                would trigger 429 errors.
        """
        plan = build_analyst_execution_plan(selected_analysts)

        analyst_factories = {
            "market": lambda: create_market_analyst(self.quick_thinking_llm),
            "social": lambda: create_sentiment_analyst(self.quick_thinking_llm),
            "news": lambda: create_news_analyst(self.quick_thinking_llm),
            "fundamentals": lambda: create_fundamentals_analyst(self.quick_thinking_llm),
            "valuation": lambda: create_valuation_analyst(self.deep_thinking_llm),
            "market_technician": lambda: create_market_technician(self.quick_thinking_llm),
        }

        # Create researcher and manager nodes
        # Bull/Bear use debate_llm (fast, cross-provider capable).
        # Research Manager keeps deep_thinking_llm — it synthesises and judges.
        bull_researcher_node  = create_bull_researcher(self.debate_llm)
        bear_researcher_node  = create_bear_researcher(self.debate_llm)
        research_manager_node = create_research_manager(self.deep_thinking_llm)
        trader_node           = create_trader(self.quick_thinking_llm)

        # Create risk analysis nodes
        # Aggressive/Conservative/Neutral use debate_llm; Portfolio Manager keeps deep.
        aggressive_analyst    = create_aggressive_debator(self.debate_llm)
        neutral_analyst       = create_neutral_debator(self.debate_llm)
        conservative_analyst  = create_conservative_debator(self.debate_llm)
        portfolio_manager_node = create_portfolio_manager(self.deep_thinking_llm)

        # Create workflow
        workflow = StateGraph(AgentState)

        # Quantitative Analyst (Markov 2.0) runs once at the front of every graph,
        # independent of the selected-analyst plan, and feeds a regime/edge signal
        # into the debate and decision agents via ``quantitative_report``.
        workflow.add_node("Quantitative Analyst", create_quantitative_analyst())

        if parallel_analysts:
            # ── Parallel mode (default) ──────────────────────────────────────
            # All selected analysts fire concurrently in threads; each writes to
            # its own dedicated report field so state merges are conflict-free.
            # Recommended for: OpenAI, Anthropic, Google Gemini, OpenRouter (paid).
            parallel_node = create_parallel_analysts_node(
                plan=plan,
                analyst_factories=analyst_factories,
                tool_nodes=self.tool_nodes,
            )
            workflow.add_node("Parallel Analysts", parallel_node)
        else:
            # ── Sequential mode ──────────────────────────────────────────────
            # Analysts run one at a time in the plan order. Safer for providers
            # with low per-key RPM (NVIDIA NIM free tier, local Ollama, etc.).
            for spec in plan.specs:
                workflow.add_node(spec.agent_node, analyst_factories[spec.key]())
                workflow.add_node(spec.clear_node, create_msg_delete())
                workflow.add_node(spec.tool_node, self.tool_nodes[spec.key])

        # Add other nodes
        workflow.add_node("Bull Researcher", bull_researcher_node)
        workflow.add_node("Bear Researcher", bear_researcher_node)
        workflow.add_node("Research Manager", research_manager_node)
        workflow.add_node("Trader", trader_node)
        # Risk-phase nodes: 5-advocate mode adds all three; 3-advocate mode adds Neutral only
        if debate_mode == "3":
            workflow.add_node("Neutral Analyst", neutral_analyst)
        else:
            workflow.add_node("Aggressive Analyst", aggressive_analyst)
            workflow.add_node("Conservative Analyst", conservative_analyst)
            workflow.add_node("Neutral Analyst", neutral_analyst)
        workflow.add_node("Portfolio Manager", portfolio_manager_node)

        # Define edges
        workflow.add_edge(START, "Quantitative Analyst")

        if parallel_analysts:
            # Parallel mode: Quant → Parallel Analysts (all at once) → Bull
            workflow.add_edge("Quantitative Analyst", "Parallel Analysts")
            workflow.add_edge("Parallel Analysts", "Bull Researcher")
        else:
            # Sequential mode: Quant → first analyst → … → last analyst → Bull
            workflow.add_edge("Quantitative Analyst", plan.specs[0].agent_node)
            for i, spec in enumerate(plan.specs):
                workflow.add_conditional_edges(
                    spec.agent_node,
                    getattr(self.conditional_logic, f"should_continue_{spec.key}"),
                    [spec.tool_node, spec.clear_node],
                )
                workflow.add_edge(spec.tool_node, spec.agent_node)
                if i < len(plan.specs) - 1:
                    workflow.add_edge(spec.clear_node, plan.specs[i + 1].agent_node)
                else:
                    workflow.add_edge(spec.clear_node, "Bull Researcher")

        # Both research-debate edges share the complete DEBATE_PATH_MAP (#1088).
        for debate_node in ("Bull Researcher", "Bear Researcher"):
            workflow.add_conditional_edges(
                debate_node,
                self.conditional_logic.should_continue_debate,
                DEBATE_PATH_MAP,
            )
        workflow.add_edge("Research Manager", "Trader")
        if debate_mode == "3":
            # 3-advocate mode: Neutral Analyst is the sole risk reviewer.
            # Trader → Neutral Analyst → Portfolio Manager (single pass, no rotation).
            workflow.add_edge("Trader", "Neutral Analyst")
            workflow.add_conditional_edges(
                "Neutral Analyst",
                self.conditional_logic.should_continue_risk_analysis_3adv,
                {"Portfolio Manager": "Portfolio Manager"},
            )
        else:
            # 5-advocate mode: full Aggressive → Conservative → Neutral rotation.
            workflow.add_edge("Trader", "Aggressive Analyst")
            # All three risk edges share the complete RISK_ANALYSIS_PATH_MAP (#1088).
            for risk_node in ("Aggressive Analyst", "Conservative Analyst", "Neutral Analyst"):
                workflow.add_conditional_edges(
                    risk_node,
                    self.conditional_logic.should_continue_risk_analysis,
                    RISK_ANALYSIS_PATH_MAP,
                )

        workflow.add_edge("Portfolio Manager", END)

        return workflow
