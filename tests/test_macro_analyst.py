"""Gap 1: Macro Analyst is a sequential Stage-1 node, carved out of News.

Quant → Macro Analyst → Parallel Analysts → Bull. Macro is not a
selected_analysts / Parallel Analysts key.
"""
import inspect
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda
from langgraph.prebuilt import ToolNode

import tradingagents.agents.analysts.macro_analyst as ma
import tradingagents.agents.analysts.news_analyst as na
from tradingagents.agents import create_macro_analyst
from tradingagents.graph.analyst_execution import build_analyst_execution_plan
from tradingagents.graph.conditional_logic import ConditionalLogic
from tradingagents.graph.propagation import Propagator
from tradingagents.graph.setup import GraphSetup
from tradingagents.graph.trading_graph import TradingAgentsGraph


@pytest.mark.unit
def test_macro_prompt_is_top_down_gate():
    src = inspect.getsource(ma)
    assert "get_macro_indicators(indicator, curr_date, look_back_days)" in src
    assert "get_global_news(curr_date, look_back_days, limit)" in src
    assert "get_prediction_markets(topic, limit)" in src
    assert "risk-off" in src
    assert "FOMC" in src
    assert "cyclical" in src
    assert "single-name" in src
    assert "ticker-specific" in src
    assert "get_news(" not in src


@pytest.mark.unit
def test_macro_factory_writes_macro_report_only():
    llm = MagicMock()
    llm.bind_tools.return_value = RunnableLambda(
        lambda _: AIMessage(content="Rates higher; risk-off off.")
    )

    node = create_macro_analyst(llm)
    out = node(
        {
            "trade_date": "2026-09-02",
            "company_of_interest": "AAPL",
            "asset_type": "stock",
            "instrument_context": "The instrument to analyze is `AAPL`.",
            "messages": [("human", "AAPL")],
        }
    )

    assert set(out) == {"messages", "macro_report"}
    assert out["macro_report"] == "Rates higher; risk-off off."
    bound_tools = llm.bind_tools.call_args[0][0]
    assert {t.name for t in bound_tools} == {
        "get_macro_indicators",
        "get_global_news",
        "get_prediction_markets",
    }


@pytest.mark.unit
def test_news_factory_drops_macro_and_prediction_market_tools():
    llm = MagicMock()
    llm.bind_tools.return_value = RunnableLambda(
        lambda _: AIMessage(content="Headlines only.")
    )

    node = na.create_news_analyst(llm)
    out = node(
        {
            "trade_date": "2026-09-02",
            "company_of_interest": "AAPL",
            "asset_type": "stock",
            "instrument_context": "The instrument to analyze is `AAPL`.",
            "messages": [("human", "AAPL")],
        }
    )

    assert "news_report" in out
    assert "macro_report" not in out
    bound_tools = llm.bind_tools.call_args[0][0]
    names = {t.name for t in bound_tools}
    assert names == {"get_news", "get_global_news"}
    assert "get_macro_indicators" not in names
    assert "get_prediction_markets" not in names


@pytest.mark.unit
def test_macro_toolnode_owns_fred_and_event_odds():
    nodes = TradingAgentsGraph._create_tool_nodes(None)
    assert "macro" in nodes
    macro_tools = set(nodes["macro"].tools_by_name)
    assert {
        "get_macro_indicators",
        "get_global_news",
        "get_prediction_markets",
    } <= macro_tools
    news_tools = set(nodes["news"].tools_by_name)
    assert "get_news" in news_tools
    assert "get_global_news" in news_tools
    assert "get_macro_indicators" not in news_tools
    assert "get_prediction_markets" not in news_tools


@pytest.mark.unit
def test_macro_report_initialized_empty():
    state = Propagator().create_initial_state("AAPL", "2026-09-02")
    assert state["macro_report"] == ""


def _graph_setup():
    llm = MagicMock()
    tool_nodes = {
        "market": ToolNode([]),
        "social": ToolNode([]),
        "news": ToolNode([]),
        "fundamentals": ToolNode([]),
        "valuation": ToolNode([]),
        "market_technician": ToolNode([]),
        "macro": ToolNode([]),
    }
    return GraphSetup(llm, llm, llm, tool_nodes, ConditionalLogic())


def _edge_pairs(workflow):
    compiled = workflow.compile()
    return {(e.source, e.target) for e in compiled.get_graph().edges}


@pytest.mark.unit
def test_parallel_graph_order_quant_macro_then_parallel_then_bull():
    workflow = _graph_setup().setup_graph(
        ["market", "news"],
        parallel_analysts=True,
    )
    nodes = set(workflow.nodes)
    assert "Macro Analyst" in nodes
    assert "tools_macro" in nodes
    assert "Msg Clear Macro" in nodes
    assert "Parallel Analysts" in nodes
    assert "Quantitative Analyst" in nodes
    # Macro must not be folded into the selected-analyst plan.
    plan = build_analyst_execution_plan(["market", "news"])
    assert all(spec.key != "macro" for spec in plan.specs)

    edges = _edge_pairs(workflow)
    assert ("__start__", "Quantitative Analyst") in edges
    assert ("Quantitative Analyst", "Macro Analyst") in edges
    assert ("tools_macro", "Macro Analyst") in edges
    assert ("Msg Clear Macro", "Parallel Analysts") in edges
    assert ("Parallel Analysts", "Bull Researcher") in edges
    assert ("Quantitative Analyst", "Parallel Analysts") not in edges


@pytest.mark.unit
def test_sequential_graph_order_quant_macro_then_first_selected():
    workflow = _graph_setup().setup_graph(
        ["news", "market"],
        parallel_analysts=False,
    )
    edges = _edge_pairs(workflow)
    assert ("Quantitative Analyst", "Macro Analyst") in edges
    assert ("Msg Clear Macro", "News Analyst") in edges
    assert ("Msg Clear News", "Market Analyst") in edges
    assert ("Msg Clear Market", "Bull Researcher") in edges
    assert ("Quantitative Analyst", "News Analyst") not in edges


@pytest.mark.unit
def test_should_continue_macro_routes_tool_loop():
    logic = ConditionalLogic()
    with_tools = AIMessage(content="", tool_calls=[{"name": "get_macro_indicators", "args": {}, "id": "1"}])
    without_tools = AIMessage(content="done")
    assert logic.should_continue_macro({"messages": [with_tools]}) == "tools_macro"
    assert logic.should_continue_macro({"messages": [without_tools]}) == "Msg Clear Macro"
