from starlette.testclient import TestClient
from tomcat_web_mcp.app import create_app

SECRET = "test-service-secret-01234567890123456789"


def test_agent_and_mcp_reject_missing_credentials_and_browser_origin():
    with TestClient(create_app(service_secret=SECRET)) as client:
        assert client.get('/health').json()['tools'] == 16
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
