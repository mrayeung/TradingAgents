"""
Parallel analyst orchestrator.

Replaces the sequential analyst chain (Market → News → Fundamentals → …) with
a **single** LangGraph node that fires all selected analysts concurrently in
threads.

Key design decisions
────────────────────
* **Isolated message buffer per analyst.**  Every analyst gets its own
  ``messages`` list that starts from a context-anchored placeholder (matching
  what ``create_msg_delete`` injects between sequential analysts).  The shared
  ``AgentState.messages`` field is *never written* by this node, so the
  parallel writes are conflict-free and the merged state stays clean for the
  debate phase that follows.

* **Report fields are naturally conflict-free.**  Each analyst writes to its
  own dedicated field (``market_report``, ``news_report``, etc.), so merging
  the ThreadPoolExecutor results into the parent state requires no locking.

* **LangChain LLM clients are stateless.**  ``ChatOpenAI`` and the bound-tool
  chains it produces are safe to call from multiple threads simultaneously.
  Callbacks may see minor imprecision in aggregate-stats counting, but that
  does not affect report content or routing.

* **Failure isolation.**  If one analyst's thread raises, the others continue.
  The failed analyst's report field receives a bracketed error placeholder so
  downstream debate agents can still run.

Rate-limit note
───────────────
Running 3–6 analysts concurrently multiplies your outbound RPM by that factor.
Most API tiers (OpenRouter, Gemini, OpenAI) can absorb this easily for one
portfolio run.  If you hit 429 errors, reduce ``max_analysis_workers`` in
``default_config.py`` or reduce the number of selected analysts.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from langchain_core.messages import HumanMessage
from langgraph.prebuilt import ToolNode

from .analyst_execution import AnalystExecutionPlan

logger = logging.getLogger(__name__)

# Safety cap on tool-call iterations per analyst thread.
# Analyst nodes normally finish within 3–5 tool-call rounds; 20 is a generous
# upper bound that prevents a runaway tool loop from hanging the whole run.
_MAX_TOOL_ITERS = 20

# Per-analyst hard timeout in seconds passed to Future.result().
# 10 minutes is comfortably above the worst-case single-analyst LLM latency.
_ANALYST_TIMEOUT_SECS = 600


def _run_single_analyst(
    *,
    analyst_fn,
    tool_node: ToolNode,
    base_state: dict,
    report_key: str,
    analyst_label: str,
) -> dict:
    """Run one analyst's full tool-call loop with an isolated message buffer.

    The analyst function and tool node are called exactly as LangGraph would
    call them in the sequential graph — the only difference is that ``messages``
    is a private list owned by this thread, not the shared ``AgentState.messages``.

    Returns
    -------
    dict
        A single-key dict, e.g. ``{"market_report": "..."}``, ready to be
        merged into the parent ``AgentState`` by the caller.
    """
    # Context-anchored placeholder — mirrors what create_msg_delete() injects
    # between sequential analysts so the LLM prompt stays correctly scoped.
    instrument_context = base_state.get("instrument_context", "")
    trade_date = base_state.get("trade_date", "the requested date")
    placeholder = HumanMessage(
        content=(
            f"Proceed with your assigned analysis for this workflow. "
            f"{instrument_context} The analysis date is {trade_date}."
        )
    )

    # Private state — a shallow copy of base_state with its own messages list.
    # Mutations to local_state never touch the original base_state dict or the
    # shared AgentState.messages list in the parent graph.
    local_state: dict = {**base_state, "messages": [placeholder]}
    report = ""

    for iteration in range(_MAX_TOOL_ITERS):
        # ── LLM call ────────────────────────────────────────────────────────
        # analyst_fn returns {"messages": [ai_msg], report_key: "..."}.
        # report_key is only populated when the analyst has finished
        # (i.e. the response has no tool calls).
        update = analyst_fn(local_state)

        new_messages = update.get("messages", [])
        local_state["messages"] = local_state["messages"] + (
            new_messages if isinstance(new_messages, list) else [new_messages]
        )

        # Capture report text if the analyst wrote it this round.
        candidate = update.get(report_key, "")
        if candidate:
            report = candidate

        # ── Check for tool calls ─────────────────────────────────────────────
        last_msg = local_state["messages"][-1]
        if not getattr(last_msg, "tool_calls", None):
            # No pending tool calls — analyst is done.
            logger.debug(
                "[parallel] %s done after %d iteration(s)", analyst_label, iteration + 1
            )
            break

        # ── Execute tool calls ───────────────────────────────────────────────
        try:
            tool_result = tool_node.invoke({"messages": local_state["messages"]})
            tool_messages = tool_result.get("messages", [])
            local_state["messages"] = local_state["messages"] + (
                tool_messages if isinstance(tool_messages, list) else [tool_messages]
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[parallel] %s tool execution failed (iter %d): %s",
                analyst_label,
                iteration,
                exc,
                exc_info=True,
            )
            break

    else:
        # Reached the iteration cap — log a warning but don't crash.
        logger.warning(
            "[parallel] %s hit %d-iteration cap; report may be incomplete",
            analyst_label,
            _MAX_TOOL_ITERS,
        )

    return {report_key: report}


def create_parallel_analysts_node(
    plan: AnalystExecutionPlan,
    analyst_factories: dict,
    tool_nodes: dict[str, ToolNode],
) -> callable:
    """Return a single LangGraph node function that runs all analysts in parallel.

    The returned node replaces the entire sequential analyst chain in the graph.
    It fans out to all selected analysts concurrently, waits for all to finish,
    and returns a dict of {report_key: report_text} entries for the parent
    AgentState to merge.

    Parameters
    ----------
    plan:
        AnalystExecutionPlan from ``build_analyst_execution_plan``.
    analyst_factories:
        Dict of key → zero-arg callable that returns an analyst node function.
        Example: ``{"market": lambda: create_market_analyst(llm), ...}``
    tool_nodes:
        Dict of key → ToolNode, one per analyst type.

    Returns
    -------
    callable
        A node function ``(state) → dict`` compatible with
        ``workflow.add_node``.
    """

    def parallel_analysts_node(state: dict) -> dict:
        # Build the task list from the execution plan.
        tasks = []
        for spec in plan.specs:
            if spec.key not in analyst_factories:
                logger.error(
                    "[parallel] unknown analyst key %r — skipping", spec.key
                )
                continue
            if spec.key not in tool_nodes:
                logger.error(
                    "[parallel] no tool_node for key %r — skipping", spec.key
                )
                continue
            # Instantiate the analyst function fresh per run (each call to the
            # factory closes over the LLM but creates a new chain / prompt).
            analyst_fn = analyst_factories[spec.key]()
            tasks.append((spec, analyst_fn, tool_nodes[spec.key]))

        if not tasks:
            logger.error("[parallel] no analysts to run — returning empty state")
            return {}

        n_workers = min(len(tasks), 6)
        logger.info(
            "[parallel] launching %d analyst(s) with %d worker(s): %s",
            len(tasks),
            n_workers,
            ", ".join(spec.agent_node for spec, *_ in tasks),
        )

        merged: dict = {}

        with ThreadPoolExecutor(max_workers=n_workers) as executor:
            future_to_spec = {
                executor.submit(
                    _run_single_analyst,
                    analyst_fn=analyst_fn,
                    tool_node=tool_node,
                    base_state=state,
                    report_key=spec.report_key,
                    analyst_label=spec.agent_node,
                ): spec
                for spec, analyst_fn, tool_node in tasks
            }

            for future in as_completed(future_to_spec):
                spec = future_to_spec[future]
                try:
                    result = future.result(timeout=_ANALYST_TIMEOUT_SECS)
                    merged.update(result)
                    report_preview = (result.get(spec.report_key, "") or "")[:80]
                    logger.info(
                        "[parallel] ✓ %s — %s…",
                        spec.agent_node,
                        report_preview.replace("\n", " "),
                    )
                except TimeoutError:
                    logger.error(
                        "[parallel] ✗ %s timed out after %ds",
                        spec.agent_node,
                        _ANALYST_TIMEOUT_SECS,
                    )
                    merged[spec.report_key] = (
                        f"[{spec.agent_node} timed out after "
                        f"{_ANALYST_TIMEOUT_SECS // 60} minutes]"
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.error(
                        "[parallel] ✗ %s raised: %s",
                        spec.agent_node,
                        exc,
                        exc_info=True,
                    )
                    merged[spec.report_key] = (
                        f"[{spec.agent_node} failed: {exc}]"
                    )

        logger.info(
            "[parallel] all analysts done — reports written: %s",
            list(merged.keys()),
        )
        return merged

    return parallel_analysts_node
