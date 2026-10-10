import httpx
import pytest
from tomcat_web_mcp.client import WebEditorClient
from tomcat_web_mcp.catalog import BY_NAME
from tomcat_web_mcp.agent import skill_instructions
from pathlib import Path
import re
from tomcat_skills.tools import BY_NAME as UPSTREAM_TOOLS


async def test_schema_rejects_unsupported_and_unknown_arguments():
    def unexpected(request):
        pytest.fail("Invalid tools must not reach the broker")
    async with httpx.AsyncClient(transport=httpx.MockTransport(unexpected)) as http:
        client = WebEditorClient(http, "http://backend", "secret")
        for name in UPSTREAM_TOOLS.keys() - BY_NAME.keys():
            assert (await client.call(name, {}))["error"]["code"] == "UNSUPPORTED_TOOL"
        assert (await client.call("entity_create", {"name": "Player", "projectId": "other"}))["error"]["code"] == "INVALID_ARGUMENT"
        assert (await client.call("entity_get", {"entity_id": 123}))["error"]["code"] == "INVALID_ARGUMENT"
        assert (await client.call("script_write", {"path": "Assets/Scripts/Test.cs", "text": ""}))["error"]["code"] == "INVALID_ARGUMENT"
        assert (await client.call("script_attach", {"entity_id": 123, "path": "Assets/Scripts/Test.cs", "scene_version": "1:3", "source_version": "hash"}))["error"]["code"] == "INVALID_ARGUMENT"
        assert (await client.call("script_read", {"path": "Packages/private.cs"}))["error"]["code"] == "INVALID_ARGUMENT"


async def test_unknown_outcome_has_stable_retry_id_and_no_automatic_retry():
    sent = []
    def handler(request):
        import json
        sent.append(json.loads(request.content))
        if len(sent) == 1:
            raise httpx.ReadTimeout("test timeout")
        return httpx.Response(200, json={"ok": True, "data": {"entity": {"id": "18446744073709551615"}}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = WebEditorClient(http, "http://backend", "secret")
        result = await client.call("entity_create", {"name": "Player", "scene_version": "1:3"})
        assert result["error"]["code"] == "OUTCOME_UNKNOWN"
        assert len(sent) == 1
        retry = await client.call("entity_create", {"name": "Player", "scene_version": "1:3", "request_id": result["request_id"]})
        assert retry["ok"]
        assert sent[0]["requestId"] == sent[1]["requestId"]
        assert sent[0]["arguments"] == sent[1]["arguments"]
        assert sent[1]["isRetry"] is True


async def test_revocation_is_not_reported_as_success():
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(401))) as http:
        result = await WebEditorClient(http, "http://backend", "revoked").call("editor_get_status", {})
        assert result["error"]["code"] == "SESSION_MISMATCH"


def test_capability_subset_and_installed_skill():
    assert len(BY_NAME) == 31
    assert not {"scene_save", "console_get_entries", "editor_step"} & BY_NAME.keys()
    assert "Query `component_get_schema`" in skill_instructions()


def test_catalog_matches_browser_capabilities():
    frontend = Path(__file__).resolve().parents[2] / "Tc_Engine_Web_Front/src/engine/automation.ts"
    source = frontend.read_text(encoding="utf-8")
    declaration = re.search(r"export const supportedTools = \[(.*?)\] as const", source, re.S)
    assert declaration is not None
    server_tools = {"project_knowledge_list", "project_knowledge_save"}
    gateways = {"capability_search", "capability_describe", "capability_invoke"}
    browser_tools = set(re.findall(r"'([^']+)'", declaration.group(1)))
    assert browser_tools | server_tools | gateways == BY_NAME.keys()
    backend = frontend.parents[3] / "Tc_Engine_Web_backend/TomCat.Api/EditorSessions.cs"
    allowed = re.search(r"HashSet<string> Tools = \[(.*?)\];", backend.read_text(encoding="utf-8"), re.S)
    assert set(re.findall(r'"([^"]+)"', allowed.group(1))) == browser_tools | server_tools
    # The upgraded package must contain workflow schemas, without exposing them on Web.
    assert {"project_create", "runtime_start", "build_player", "scene_save_as"} <= UPSTREAM_TOOLS.keys()
