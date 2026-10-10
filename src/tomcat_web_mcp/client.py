import uuid
import httpx
from jsonschema import Draft202012Validator
from .catalog import BY_NAME


def failure(code, message, request_id=None):
    result = {"ok": False, "error": {"code": code, "message": message}}
    if request_id:
        result["request_id"] = request_id
    return result


class WebEditorClient:
    def __init__(self, http: httpx.AsyncClient, backend_url: str, token: str):
        self.http, self.backend_url = http, backend_url.rstrip("/")
        self.headers = {"Authorization": f"Bearer {token}"}

    async def identity(self):
        response = await self.http.get(f"{self.backend_url}/internal/editor-session", headers=self.headers)
        response.raise_for_status()
        return response.json()

    async def call(self, name, arguments):
        if name not in BY_NAME:
            return failure("UNSUPPORTED_TOOL", "Tool is unavailable in the Web editor.")
        if not isinstance(arguments, dict):
            return failure("INVALID_ARGUMENT", "Arguments must be an object.")
        errors = list(Draft202012Validator(BY_NAME[name]["inputSchema"]).iter_errors(arguments))
        if errors:
            return failure("INVALID_ARGUMENT", errors[0].message)
        if name.startswith("capability_"):
            capabilities = {key: value for key, value in BY_NAME.items() if not key.startswith("capability_")}
            if name == "capability_invoke":
                if arguments["name"] not in capabilities:
                    return failure("UNSUPPORTED_TOOL", "Unknown executable capability")
                return await self.call(arguments["name"], arguments["arguments"])
            if name == "capability_describe":
                selected = capabilities.get(arguments["name"])
                return {"ok": True, "data": {"version": 1, **selected}} if selected else failure("UNSUPPORTED_TOOL", "Unknown capability")
            query = arguments["query"].lower()
            for word, replacement in {"场景": "scene", "实体": "entity", "组件": "component", "脚本": "script", "物理": "runtime", "physics": "runtime", "知识": "knowledge", "差异": "diff", "批量": "patch"}.items():
                query = query.replace(word, f" {replacement} ")
            terms = query.split()
            ranked = sorted(capabilities.values(), key=lambda t: sum(term in (t["name"] + " " + t["description"]).lower() for term in terms), reverse=True)
            matches = [t for t in ranked if not terms or any(term in (t["name"] + " " + t["description"]).lower() for term in terms)]
            return {"ok": True, "data": {"capabilities": [{"name": t["name"], "version": 1, "description": t["description"], "readOnly": t["annotations"].get("readOnlyHint", False)} for t in matches[:12]], "total": len(matches)}}
        args = dict(arguments)
        retry_id = args.pop("request_id", None)
        request_id = retry_id or uuid.uuid4().hex
        try:
            response = await self.http.post(f"{self.backend_url}/internal/editor-session/call", headers=self.headers,
                json={"requestId": request_id, "name": name, "arguments": args, "isRetry": retry_id is not None}, timeout=125 if name in ("script_compile", "editor_play", "runtime_validate") else 35)
            if response.status_code == 401:
                return failure("SESSION_MISMATCH", "Editor lease expired or was revoked. Reconnect and inspect the scene.", request_id)
            response.raise_for_status()
            result = response.json()
            if not isinstance(result, dict) or type(result.get("ok")) is not bool:
                return failure("OUTCOME_UNKNOWN", "Invalid editor reply. Inspect the scene before further writes.", request_id)
            result["request_id"] = request_id
            if name == "editor_get_status" and result["ok"]:
                result["data"].update(await self.identity())
            return result
        except (httpx.HTTPError, ValueError):
            return failure("OUTCOME_UNKNOWN", "Transport failed. Retry only with this request_id and the original arguments, or inspect the scene.", request_id)
