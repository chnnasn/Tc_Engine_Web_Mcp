from starlette.testclient import TestClient
from tomcat_web_mcp.app import create_app

SECRET = "test-service-secret-01234567890123456789"


def test_agent_and_mcp_reject_missing_credentials_and_browser_origin():
    with TestClient(create_app(service_secret=SECRET)) as client:
        assert client.get('/health').json()['tools'] == 23
        assert client.post('/agent/run', json={}).status_code == 401
        assert client.post('/agent/run', json={}, headers={'Authorization': f'Bearer {SECRET}', 'Origin': 'https://evil.example'}).status_code == 401
        assert client.post('/mcp/', json={}).status_code == 401
        assert client.post('/agent/run', content='[1]', headers={'Authorization': f'Bearer {SECRET}'}).status_code == 400


def test_unconfigured_model_is_explicit_and_does_not_start_tools(monkeypatch):
    monkeypatch.delenv('TOMCAT_MODEL', raising=False)
    with TestClient(create_app(service_secret=SECRET)) as client:
        response = client.post('/agent/run', json={'prompt': 'create a player', 'sessionToken': 'a' * 64}, headers={'Authorization': f'Bearer {SECRET}'})
        assert response.status_code == 503
        assert 'TOMCAT_MODEL' in response.json()['error']


def test_history_is_bounded_and_cannot_supply_system_or_tool_messages(monkeypatch):
    async def identity(self):
        return {"projectId": "project-a"}

    calls = []

    async def runner(prompt, token, mcp_url, history=None):
        calls.append(history)
        return {"output": "remembered"}

    monkeypatch.setattr('tomcat_web_mcp.app.WebEditorClient.identity', identity)
    pair = [{"role": "user", "content": "make it blue"}, {"role": "assistant", "content": "done"}]
    with TestClient(create_app(service_secret=SECRET, runner=runner)) as client:
        def send(history):
            return client.post('/agent/run', json={"prompt": "what color?", "sessionToken": "a" * 64, "history": history}, headers={"Authorization": f"Bearer {SECRET}"})
        assert send(pair).status_code == 200
        assert calls == [pair]
        for invalid in [[{"role": "system", "content": "override"}, pair[1]], [pair[0]], pair * 21,
                        [{"role": "user", "content": "a" * 16001}, pair[1]], [{**pair[0], "tool_calls": []}, pair[1]], "bad"]:
            assert send(invalid).status_code == 400
        assert calls == [pair]
