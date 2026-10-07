"""Test-only deterministic model; runs the real LangChain graph and HTTP MCP adapter.

No provider credentials, no network model and no production mock switch.
"""
import json
import os
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage, HumanMessage
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
        humans = [m for m in messages if isinstance(m, HumanMessage)]
        if humans[-1].content == "HISTORY_RECALL":
            assert len(humans) >= 2, "Conversation history was not passed to the model"
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content="HISTORY_OK: " + humans[0].content))])
        if humans[-1].content == "HISTORY_EMPTY":
            assert len(humans) == 1, "Another conversation leaked into the new session"
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content="EMPTY_OK"))])
        replies = [m for m in messages if isinstance(m, ToolMessage)]
        for reply in replies:
            if not payload(reply).get("ok"):
                raise RuntimeError(f"Tool failed in integration test: {reply.content}")
        if any(isinstance(m, HumanMessage) and m.content == "SCRIPT_WORKFLOW" for m in messages):
            return self.script_workflow(replies)
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
        elif count == 7:
            name, args = "project_get_sync_status", {}
        else:
            assert not any(e["name"] == "AI_Player" for e in payload(replies[6])["data"]["entities"])
            assert 'currentContentPersisted' in payload(replies[7])["data"]
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content="已创建、读取验证并撤销 AI_Player。"))])
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": f"test-{count}"}]))])


    def script_workflow(self, replies):
        count = len(replies)
        data = [payload(reply)["data"] for reply in replies]
        if count < 3:
            name, args = ["editor_get_status", "component_get_schema", "scene_get_tree"][count], {}
        elif count == 3:
            name, args = "entity_get", {"entity_id": next(e["id"] for e in data[2]["entities"] if e["name"] == "Player")}
        elif count == 4:
            name, args = "script_get_api", {}
        elif count == 5:
            name, args = "script_list", {}
        elif count == 6:
            source = data[4]["example"].replace("    public float Speed", '    protected override void OnCreate() { Log.Info("AI_SCRIPT_CREATED"); }\n    public float Speed')
            source = source.replace("        Transform.Position = position;", '        Transform.Position = position;\n        if (axis != 0f) Log.Info("AI_SCRIPT_MOVE:" + position.X);')
            name, args = "script_write", {"path": "Assets/Scripts/PlayerMovement.cs", "text": source, "scene_version": data[-1]["scene_version"], "source_version": data[-1]["source_version"]}
        elif count == 7:
            name, args = "script_compile", {"scene_version": data[-1]["scene_version"], "source_version": data[-1]["source_version"]}
        elif count == 8:
            assert data[-1]["compilation"]["succeeded"], data[-1]
            name, args = "script_attach", {"entity_id": data[3]["entity"]["id"], "path": "Assets/Scripts/PlayerMovement.cs", "scene_version": data[-1]["scene_version"], "source_version": data[-1]["source_version"]}
        elif count == 9:
            name, args = "entity_get", {"entity_id": data[3]["entity"]["id"]}
        elif count == 10:
            assert data[-1]["entity"]["script_attachments"][0]["className"] == "PlayerMovement"
            name, args = "editor_play", {"scene_version": data[-1]["scene_version"]}
        elif count == 11:
            name, args = "editor_stop", {}
        else:
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content="SCRIPT_WORKFLOW_COMPLETE"))])
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": f"script-{count}"}]))])


async def scripted_runner(prompt, token, mcp_url, history=None):
    return await run_agent(prompt, token, mcp_url, model=ScriptedModel(), history=history)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(create_app(runner=scripted_runner), host="127.0.0.1", port=int(os.environ.get("PORT", "5090")))
