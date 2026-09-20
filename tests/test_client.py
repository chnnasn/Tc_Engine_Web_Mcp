import httpx
import pytest
from tomcat_web_mcp.client import WebEditorClient
from tomcat_web_mcp.catalog import BY_NAME
from tomcat_web_mcp.agent import skill_instructions


async def test_schema_rejects_unsupported_and_unknown_arguments():
    def unexpected(request):
        pytest.fail("Invalid tools must not reach the broker")
    async with httpx.AsyncClient(transport=httpx.MockTransport(unexpected)) as http:
        client = WebEditorClient(http, "http://backend", "secret")
        assert (await client.call("scene_save", {}))["error"]["code"] == "UNSUPPORTED_TOOL"
        assert (await client.call("entity_create", {"name": "Player", "projectId": "other"}))["error"]["code"] == "INVALID_ARGUMENT"
        assert (await client.call("entity_get", {"entity_id": 123}))["error"]["code"] == "INVALID_ARGUMENT"


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
    assert len(BY_NAME) == 16
    assert not {"scene_save", "console_get_entries", "editor_step"} & BY_NAME.keys()
    assert "Query `component_get_schema`" in skill_instructions()
