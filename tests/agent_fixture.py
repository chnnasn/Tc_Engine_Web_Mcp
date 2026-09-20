"""Test-only deterministic model; runs the real LangChain graph and HTTP MCP adapter.

No provider credentials, no network model and no production mock switch.
"""
import json
import os
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from tomcat_web_mcp.agent import run_agent
from tomcat_web_mcp.app import create_app


def payload(message):
    content = message.content
    if isinstance(content, list):
        content = next(block["text"] for block in content if block.get("type") == "text")
    return json.loads(content)


class ScriptedModel(BaseChatModel):
    @property
    def _llm_type(self):
        return "tomcat-test-scripted"

    def bind_tools(self, tools, **kwargs):
        assert {"entity_create", "entity_get", "history_undo"} <= {tool.name for tool in tools}
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        replies = [m for m in messages if isinstance(m, ToolMessage)]
        for reply in replies:
            if not payload(reply).get("ok"):
                raise RuntimeError(f"Tool failed in integration test: {reply.content}")
        count = len(replies)
        if count < 3:
            name, args = ["editor_get_status", "component_get_schema", "scene_get_tree"][count], {}
        elif count == 3:
            name, args = "entity_create", {"name": "AI_Player", "scene_version": payload(replies[-1])["data"]["scene_version"]}
        elif count == 4:
            name, args = "entity_get", {"entity_id": payload(replies[-1])["data"]["entity"]["id"]}
        elif count == 5:
            name, args = "history_undo", {"scene_version": payload(replies[-1])["data"]["scene_version"]}
        elif count == 6:
            name, args = "scene_get_tree", {}
        else:
            assert not any(e["name"] == "AI_Player" for e in payload(replies[-1])["data"]["entities"])
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content="已创建、读取验证并撤销 AI_Player。"))])
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": f"test-{count}"}]))])


async def scripted_runner(prompt, token, mcp_url):
    return await run_agent(prompt, token, mcp_url, model=ScriptedModel())


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(create_app(runner=scripted_runner), host="127.0.0.1", port=int(os.environ.get("PORT", "5090")))
