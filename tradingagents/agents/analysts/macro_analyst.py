from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from tradingagents.agents.utils.agent_utils import (
    get_global_news,
    get_instrument_context_from_state,
    get_language_instruction,
    get_macro_indicators,
    get_prediction_markets,
)


def create_macro_analyst(llm):
    def macro_analyst_node(state):
        current_date = state["trade_date"]
        instrument_context = get_instrument_context_from_state(state)

        tools = [
            get_macro_indicators,
            get_global_news,
            get_prediction_markets,
        ]

        system_message = (
            "You are the Macro Analyst. You own top-down macro framing for the desk "
            "so the News Analyst can stay headlines-only. Write a Stage-1 gate that covers: "
            "policy rates and the USD; credit conditions; EM risk; the macro calendar "
            "(FOMC, CPI, and other high-impact prints); whether the tape favors cyclical or "
            "defensive sectors; and an explicit **risk-off** flag (on/off) with the evidence "
            "that justifies it. "
            "Use get_macro_indicators(indicator, curr_date, look_back_days) to ground commentary "
            "in FRED data (e.g. 'cpi', 'core_pce', 'unemployment', 'fed_funds_rate', "
            "'10y_treasury', 'yield_curve', 'vix'). "
            "Optionally use get_global_news(curr_date, look_back_days, limit) only for desk/macro "
            "context (central-bank, rates, FX, credit, EM) — never for single-name or "
            "ticker-specific headlines. "
            "Optionally use get_prediction_markets(topic, limit) for Fed/recession event odds. "
            "Do NOT analyze, fetch, or cite single-name headlines or ticker-specific news. "
            "You may use the instrument's sector/industry from context only to judge cyclical "
            "vs defensive implications. Provide specific, actionable insights with supporting "
            "evidence to help traders make informed decisions."
            + """ Make sure to append a Markdown table at the end of the report to organize key points in the report, organized and easy to read."""
            + get_language_instruction()
        )

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are a helpful AI assistant, collaborating with other assistants."
                    " Use the provided tools to progress towards answering the question."
                    " If you are unable to fully answer, that's OK; another assistant with different tools"
                    " will help where you left off. Execute what you can to make progress."
                    " If you or any other assistant has the FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** or deliverable,"
                    " prefix your response with FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** so the team knows to stop."
                    " You have access to the following tools: {tool_names}."
                    " Today's date is {current_date}; treat it as 'now' for all analysis and tool-call date ranges. {instrument_context}\n"
                    "{system_message}",
                ),
                MessagesPlaceholder(variable_name="messages"),
            ]
        )

        prompt = prompt.partial(system_message=system_message)
        prompt = prompt.partial(tool_names=", ".join([tool.name for tool in tools]))
        prompt = prompt.partial(current_date=current_date)
        prompt = prompt.partial(instrument_context=instrument_context)

        chain = prompt | llm.bind_tools(tools)
        result = chain.invoke(state["messages"])

        report = ""

        if len(result.tool_calls) == 0:
            report = result.content

        return {
            "messages": [result],
            "macro_report": report,
        }

    return macro_analyst_node
