import asyncio
import contextlib
import hmac
import json
import logging
import os
from contextvars import ContextVar

import httpx
import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from .agent import run_agent
from .catalog import WEB_TOOLS
from .client import WebEditorClient

credential: ContextVar[str] = ContextVar("editor_credential")


def create_app(backend_url=None, service_secret=None, mcp_url=None, runner=run_agent):
    backend_url = backend_url or os.environ.get("TOMCAT_BACKEND_URL", "http://127.0.0.1:5080")
    service_secret = service_secret or os.environ.get("TOMCAT_AGENT_SECRET", "")
    mcp_url = mcp_url or os.environ.get("TOMCAT_MCP_URL", "http://127.0.0.1:5090/mcp/")
    if len(service_secret) < 32:
        raise RuntimeError("TOMCAT_AGENT_SECRET must contain at least 32 characters")
    http = httpx.AsyncClient(timeout=10, trust_env=False)
    server = Server("tomcat-web-editor", version="0.1.0")

    @server.list_tools()
    async def list_tools():
        return [types.Tool(**tool) for tool in WEB_TOOLS]

    @server.call_tool()
    async def call_tool(name, arguments):
        client = WebEditorClient(http, backend_url, credential.get())
        result = await client.call(name, arguments)
        return types.CallToolResult(content=[types.TextContent(type="text", text=json.dumps(result, ensure_ascii=False))],
            structuredContent=result, isError=not result["ok"])

    manager = StreamableHTTPSessionManager(app=server, event_store=None, json_response=True, stateless=True)

    async def mcp_app(scope, receive, send):
        request = Request(scope)
        auth = request.headers.get("authorization", "")
        if request.headers.get("origin") or not auth.startswith("Bearer "):
            await JSONResponse({"error": "Unauthorized"}, status_code=401)(scope, receive, send)
            return
        token = auth[7:]
        try:
            await WebEditorClient(http, backend_url, token).identity()
        except (httpx.HTTPError, ValueError):
            await JSONResponse({"error": "Editor lease unavailable"}, status_code=401)(scope, receive, send)
            return
        handle = credential.set(token)
        try:
            await manager.handle_request(scope, receive, send)
        finally:
            credential.reset(handle)

    active: set[str] = set()

    async def agent_endpoint(request: Request):
        if request.headers.get("origin") or not hmac.compare_digest(request.headers.get("authorization", ""), f"Bearer {service_secret}"):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > 40000:
                return JSONResponse({"error": "Request too large"}, status_code=413)
        try:
            body = json.loads(raw)
            prompt, token = body["prompt"], body["sessionToken"]
            if not isinstance(prompt, str) or not 1 <= len(prompt.strip()) <= 8000 or not isinstance(token, str) or len(token) != 64:
                raise ValueError()
        except (ValueError, KeyError, TypeError):
            return JSONResponse({"error": "Invalid request"}, status_code=400)
        if runner is run_agent and not os.environ.get("TOMCAT_MODEL"):
            return JSONResponse({"error": "模型尚未配置，请先设置 TOMCAT_MODEL 和模型服务凭证。"}, status_code=503)
        try:
            await WebEditorClient(http, backend_url, token).identity()
        except (httpx.HTTPError, ValueError):
            return JSONResponse({"error": "Editor session unavailable"}, status_code=401)
        if token in active or len(active) >= 4:
            return JSONResponse({"error": "Agent busy"}, status_code=429)
        active.add(token)
        task = asyncio.create_task(runner(prompt, token, mcp_url))
        try:
            async with asyncio.timeout(180):
                while not task.done():
                    await asyncio.wait({task}, timeout=0.5)
                    if await request.is_disconnected():
                        task.cancel()
                        return JSONResponse({"error": "Run cancelled"}, status_code=499)
                return JSONResponse(await task)
        except TimeoutError:
            return JSONResponse({"error": "AI 执行超时，请检查场景后再继续。"}, status_code=504)
        except Exception as error:
            # Provider exceptions can contain credentials or URLs; never forward them to browsers.
            logging.getLogger(__name__).error("Agent failed (%s); inspect model configuration and editor state", type(error).__name__)
            return JSONResponse({"error": "AI 执行失败，请检查模型配置和当前场景；已完成的修改会保留。"}, status_code=502)
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
            active.discard(token)

    @contextlib.asynccontextmanager
    async def lifespan(app):
        async with http, manager.run():
            yield

    async def health(request):
        return JSONResponse({"status": "ok", "agent": "langchain", "tools": len(WEB_TOOLS), "modelConfigured": bool(os.environ.get("TOMCAT_MODEL"))})

    return Starlette(routes=[Route("/health", health), Route("/agent/run", agent_endpoint, methods=["POST"]), Mount("/mcp", app=mcp_app)], lifespan=lifespan)


def main():
    import uvicorn
    uvicorn.run(create_app(), host=os.environ.get("TOMCAT_HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "5090")))
