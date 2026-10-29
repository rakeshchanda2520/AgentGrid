"""The agent as a LangGraph StateGraph: deterministic guards around an LLM tool loop.

START → guard_in ─(rule hit)→ handover → END
             └→ agent ⇄ tools ─(handover tool)→ handover
                agent → guard_out ─(2nd low-confidence turn)→ handover
                        guard_out → END
"""

from typing import Annotated, Any, TypedDict

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage
from langchain_core.runnables import Runnable, RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from app.agent import guardrails, prompts
from app.agent.tools import turn_of


class AgentState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]


def build(bound: Runnable, tools: list, blocked_terms: list[str] | None = None):
    """`bound` is a chat model with tools already bound (optionally `.with_fallbacks(...)`)."""

    async def guard_in(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
        turn = turn_of(config)
        turn.path.append("guard_in")
        last = next((m for m in reversed(state["messages"]) if isinstance(m, HumanMessage)), None)
        if last is not None and (reason := guardrails.handover_rule(guardrails.text_of(last), turn.config["handover"])):
            turn.handover_reason = reason
        return {}

    async def agent(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
        turn = turn_of(config)
        turn.path.append("agent")
        response = await bound.ainvoke([SystemMessage(prompts.system_prompt(turn)), *state["messages"]], config)
        return {"messages": [response]}

    async def guard_out(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
        turn = turn_of(config)
        turn.path.append("guard_out")
        last = state["messages"][-1]
        text, cited = guardrails.check_citations(guardrails.text_of(last), turn.retrieved)
        turn.citations = cited
        text = guardrails.output_filter(text, blocked_terms or [])
        if turn.low_conf and not cited:
            streak = turn.conversation["low_conf_turns"] + 1
            turn.conversation["low_conf_turns"] = streak
            if streak >= turn.config["handover"].get("low_confidence_turns", 2):
                turn.handover_reason = "low confidence"
        else:
            turn.conversation["low_conf_turns"] = 0
        return {
            "messages": [AIMessage(content=text, id=last.id, response_metadata=last.response_metadata, usage_metadata=getattr(last, "usage_metadata", None))]
        }

    async def handover(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
        turn = turn_of(config)
        turn.path.append("handover")
        local = turn.now.astimezone(turn.tz)
        hours = turn.config["booking"]["hours"]
        msg = guardrails.handover_message(turn.handover_reason or "", guardrails.is_open(hours, local), hours)
        return {"messages": [AIMessage(content=msg, response_metadata={"model_name": "scripted"})]}

    async def tools_node(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
        turn_of(config).path.append("tools")
        return await tool_node.ainvoke(state, config)

    tool_node = ToolNode(tools, handle_tool_errors=True)
    g = StateGraph(AgentState)
    g.add_node("guard_in", guard_in)
    g.add_node("agent", agent)
    g.add_node("tools", tools_node)
    g.add_node("guard_out", guard_out)
    g.add_node("handover", handover)
    g.add_edge(START, "guard_in")
    g.add_conditional_edges("guard_in", lambda s, config: "handover" if turn_of(config).handover_reason else "agent", ["handover", "agent"])
    g.add_conditional_edges("agent", lambda s: "tools" if getattr(s["messages"][-1], "tool_calls", None) else "guard_out", ["tools", "guard_out"])
    g.add_conditional_edges("tools", lambda s, config: "handover" if turn_of(config).handover_reason else "agent", ["handover", "agent"])
    g.add_conditional_edges("guard_out", lambda s, config: "handover" if turn_of(config).handover_reason else END, ["handover", END])
    g.add_edge("handover", END)
    return g.compile()


def mermaid() -> str:
    from app.agent.tools import make_tools
    from app.llm import OfflineModel
    from app.templates import agent_config

    tools = make_tools({"config": agent_config("real_estate")})
    return build(OfflineModel().bind_tools(tools), tools).get_graph().draw_mermaid()
