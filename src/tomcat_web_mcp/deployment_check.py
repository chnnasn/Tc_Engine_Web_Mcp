"""Railway pre-deploy checks. No model calls or editor writes are performed."""
import os

import httpx
from starlette.testclient import TestClient

from .app import create_app


def main():
    backend = os.environ["TOMCAT_BACKEND_URL"].rstrip("/")
    with httpx.Client(trust_env=False, timeout=15) as http:
        response = http.get(backend + "/health")
        response.raise_for_status()
        if response.json().get("status") != "ok":
            raise RuntimeError("Backend health check failed")
    with TestClient(create_app()) as client:
        health = client.get("/health")
        if health.status_code != 200 or health.json().get("tools", 0) < 1:
            raise RuntimeError("MCP health check failed")
        if client.post("/mcp/", json={}).status_code != 401:
            raise RuntimeError("MCP must reject missing credentials")
        if client.post("/mcp/", json={}, headers={"Authorization": "Bearer " + "0" * 64}).status_code != 401:
            raise RuntimeError("MCP must reject invalid editor credentials")
        if client.post("/agent/run", json={}).status_code != 401:
            raise RuntimeError("Agent must reject missing credentials")
    print("Deployment checks passed: backend private HTTP, MCP health, credential rejection.", flush=True)


if __name__ == "__main__":
    main()
