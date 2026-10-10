import json
import httpx
import pytest
from tomcat_web_mcp.client import WebEditorClient


async def test_discovery_gateway_validates_nested_schema_and_preserves_retry():
    sent = []
    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"ok": True, "data": {"scene_version": "1:2"}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = WebEditorClient(http, "http://backend", "token")
        found = await client.call("capability_search", {"query": "批量"})
        assert "scene_apply_patch" in [c["name"] for c in found["data"]["capabilities"]]
        phrase = await client.call("capability_search", {"query": "批量修改场景"})
        assert phrase["data"]["capabilities"][0]["name"] == "scene_apply_patch"
        described = await client.call("capability_describe", {"name": "runtime_validate"})
        assert described["data"]["inputSchema"]["properties"]["steps"]["maximum"] == 600
        for name, args in [("shell", {}), ("capability_invoke", {}), ("scene_apply_patch", {"operations": []})]:
            assert not (await client.call("capability_invoke", {"name": name, "version": 1, "arguments": args}))["ok"]
        assert not sent
        args = {"scene_version": "1:1", "label": "create", "request_id": "original", "operations": [{"op": "entity.create", "entityId": "18446744073709551615", "name": "Box"}]}
        assert (await client.call("capability_invoke", {"name": "scene_apply_patch", "version": 1, "arguments": args}))["ok"]
        assert sent[0]["requestId"] == "original" and sent[0]["isRetry"]
        assert sent[0]["arguments"]["operations"][0]["entityId"] == "18446744073709551615"


async def test_patch_and_runtime_limits_never_reach_broker():
    def unexpected(request):
        pytest.fail("Invalid capability reached broker")
    async with httpx.AsyncClient(transport=httpx.MockTransport(unexpected)) as http:
        client = WebEditorClient(http, "http://backend", "token")
        for operations in [[], [{"op": "shell", "entityId": "1"}], [{"op": "entity.delete", "entityId": 1}], [{"op": "entity.delete", "entityId": "1"}] * 129]:
            result = await client.call("scene_apply_patch", {"scene_version": "1:1", "label": "test", "operations": operations})
            assert result["error"]["code"] == "INVALID_ARGUMENT"
        assert not (await client.call("runtime_validate", {"scene_version": "1:1", "steps": 601, "sample_every": 10, "checks": []}))["ok"]
        assert not (await client.call("project_knowledge_save", {"key": "x", "content": "hello", "expected_version": -1}))["ok"]
