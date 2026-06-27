"""
Valuation Analyst — sector-aware multi-agent equity valuation.

Workflow:
  1. Call get_valuation_metrics → understand sector + current vs. 3yr history
  2. Identify 6-10 peer tickers based on sector knowledge
  3. Call get_peer_comparables → comps table
  4. Write structured valuation report with verdict (Rich / Fair / Cheap)
"""

import json

from langchain_core.messages import HumanMessage, SystemMessage

from tradingagents.agents.utils.valuation_tools import (
    get_peer_comparables,
    get_valuation_metrics,
)


def create_valuation_analyst(llm):
    """Return a LangGraph node function for the Valuation Analyst."""

    def valuation_analyst_node(state: dict) -> dict:
        ticker: str = state["company_of_interest"]
        trade_date: str = state["trade_date"]

        tools = [get_valuation_metrics, get_peer_comparables]
        llm_with_tools = llm.bind_tools(tools)

        system_prompt = SystemMessage(
            content="""You are a sell-side equity research analyst specializing in fundamental valuation.

Your task is to write a rigorous **Valuation** section for an equity research report.
You must answer three questions:
1. Is this stock cheap or expensive vs. its **own historical multiples**?
2. Is it cheap or expensive vs. **true sector peers**?
3. What does the **sector-appropriate valuation framework** say about fair value?

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
REQUIRED WORKFLOW — follow these steps in order:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

**Step 1 — Get current + historical multiples**
Call `get_valuation_metrics` with the ticker and trade_date.
Read the output carefully:
  • Identify the sector and which metrics the framework says matter most
  • Note current multiples vs. the 3-year historical table
  • Compute where current multiples sit vs. historical range (above/below/in-line)

**Step 2 — Select 6–10 business peers**
Based on sector, industry, and company characteristics, choose genuine comparables:
  • Same sub-industry or directly adjacent
  • Similar scale (within ~0.3x–3x of target market cap)
  • Avoid simply picking S&P 500 or sector-index members — pick TRUE comps
  • For niche companies (regional banks, specialty chemicals, micro-cap), 4–5 peers is fine

**Step 3 — Get peer comps table**
Call `get_peer_comparables` with your chosen peers as a comma-separated string.

**Step 4 — Write the valuation report**

Structure your report with these exact sections:

---

### Valuation Framework
State the sector. Explain which metrics you are using and WHY they are appropriate
for this specific business model. Note any atypical factors (e.g., "pre-profit, so
P/E is not meaningful — we focus on EV/Revenue and Rule of 40").

### Current Multiples vs. Own History
Insert the historical table (pull key rows from the get_valuation_metrics output).
Add a brief narrative: "Currently trading at Xx forward P/E, vs. 3-year average of Xx
(a XX% premium/discount to its own history)."
Call out any meaningful expansion or compression in multiples over time.

### Peer Comparables
Insert the comps table from get_peer_comparables.
Narrative: where does the target rank vs. peers on the primary metrics?
Is any premium/discount justified by better/worse growth or margins?
Cite specific numbers: "NVDA trades at a 2.3x premium to peer median EV/EBITDA of 18x,
supported by 82% gross margins vs. peer median of 51%."

### Valuation Verdict
Choose exactly one: **Significantly Undervalued** / **Moderately Undervalued** /
**Fairly Valued** / **Moderately Overvalued** / **Significantly Overvalued**

Justify with 2–3 specific data points. Be precise — don't hedge excessively.
If the stock is expensive on earnings but cheap on FCF, call that out explicitly.

### Summary Table
| Metric | Current | 3yr Avg | Peer Median | vs. Own History | vs. Peers |
|--------|---------|---------|-------------|-----------------|-----------|
Fill in the key sector-appropriate multiples. Use ↑ / ↓ / = for direction.

---

TONE: Analytical, precise, sell-side quality. Use specific numbers everywhere.
Do NOT write generic statements like "the stock appears fairly valued." Show the math.
"""
        )

        human_prompt = HumanMessage(
            content=(
                f"Please perform a complete valuation analysis for **{ticker}** "
                f"as of **{trade_date}**.\n\n"
                f"Follow the workflow: call get_valuation_metrics first, then identify "
                f"peers, call get_peer_comparables, then write the full valuation report."
            )
        )

        messages = [system_prompt, human_prompt]
        result = llm_with_tools.invoke(messages)

        report = ""
        if not result.tool_calls:
            report = result.content

        return {
            "messages": messages + [result],
            "valuation_report": report,
        }

    return valuation_analyst_node
