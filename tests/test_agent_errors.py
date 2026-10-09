"""Real LangChain graph + MCP adapter: tool failures remain observations."""
import json
import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_mcp_adapters.tools import convert_mcp_tool_to_langchain_tool
from mcp.types import Tool, CallToolResult, TextContent
from tomcat_web_mcp.agent import run_agent


class RecoveryModel(BaseChatModel):
    @property
    def _llm_type(self):
        return "error-recovery-fixture"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        replies = [m for m in messages if isinstance(m, ToolMessage)]
        if not replies:
            message = AIMessage(content="", tool_calls=[{"name": "component_set", "args": {}, "id": "write-1"}])
        else:
            reply = replies[-1]
            assert reply.status == "error"
            result = json.loads(reply.content)
            assert result["ok"] is False
            assert result["request_id"] == "original-write-id"
            message = AIMessage(content="STOP_AND_INSPECT: " + result["error"]["code"])
        return ChatResult(generations=[ChatGeneration(message=message)])


@pytest.mark.parametrize("code", ["SCENE_CHANGED", "INVALID_ARGUMENT", "OUTCOME_UNKNOWN"])
async def test_mcp_errors_reach_model_without_retrying_writes(monkeypatch, code):
    calls = []

    class Session:
        async def call_tool(self, name, arguments, **kwargs):
            calls.append((name, arguments))
            result = {"ok": False, "error": {"code": code, "message": "Inspect before continuing"}, "request_id": "original-write-id"}
            return CallToolResult(content=[TextContent(type="text", text=json.dumps(result))], structuredContent=result, isError=True)

    tool = convert_mcp_tool_to_langchain_tool(Session(), Tool(name="component_set", description="fixture write", inputSchema={"type": "object", "properties": {}}))

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        async def get_tools(self):
            return [tool]

    monkeypatch.setattr("tomcat_web_mcp.agent.MultiServerMCPClient", Client)
    monkeypatch.setattr("tomcat_web_mcp.agent.skill_instructions", lambda: "")
    result = await run_agent("make player visible", "fixture", "http://fixture/mcp/", model=RecoveryModel())
    assert result["output"] == "STOP_AND_INSPECT: " + code
    assert calls == [("component_set", {})]
