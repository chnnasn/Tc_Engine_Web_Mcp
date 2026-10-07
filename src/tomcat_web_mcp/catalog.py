from copy import deepcopy
from tomcat_skills.tools import BY_NAME as UPSTREAM_TOOLS

# Do not advertise capabilities that the Web host cannot execute with the same semantics.
SUPPORTED = (
    "editor_get_status", "scene_get_tree", "entity_get", "component_get_schema",
    "entity_create", "entity_delete", "entity_reparent", "component_add",
    "component_remove", "component_set", "editor_play", "editor_pause",
    "editor_stop", "history_undo", "history_redo",
)
# Explicit lookup also fails at startup if an upstream upgrade removes a required schema.
WEB_TOOLS = [deepcopy(UPSTREAM_TOOLS[name]) for name in SUPPORTED]
for tool in WEB_TOOLS:
    properties = tool["inputSchema"]["properties"]
    if "request_id" in properties:
        properties["request_id"]["description"] = "Retry only: use the returned request_id and exactly the original arguments in this editor lease. Omit for new calls."
    if "scene_version" in properties:
        properties["scene_version"]["description"] = "Opaque version from the inspected Web scene. Pass it when writing; never parse or invent it."
WEB_TOOLS.append({"name": "project_get_sync_status", "description": "Read whether the CURRENT editor content is synced and persisted. cloudPersisted alone does not mean current edits are saved. Status may be local_changes, conflict, blocked, synced_pending_persistence or persisted. Read again after SAVE_IN_PROGRESS.",
    "inputSchema": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
    "annotations": {"readOnlyHint": True, "openWorldHint": False, "destructiveHint": False}})
def script_tool(name, description, properties=None, required=None, writes=False):
    fields = dict(properties or {})
    if writes:
        fields.update({"scene_version": {"type": "string", "description": "Latest inspected scene_version."},
                       "source_version": {"type": "string", "description": "Latest source_version from script_list/read/write/compile. Never invent."},
                       "request_id": {"type": "string", "pattern": "^[a-zA-Z0-9_-]{1,64}$", "description": "Retry only: original request_id and exactly original arguments."}})
    return {"name": name, "description": description,
            "inputSchema": {"type": "object", "properties": fields,
                            "required": list(required or []) + (["scene_version", "source_version"] if writes else []), "additionalProperties": False},
            "annotations": {"readOnlyHint": not writes, "openWorldHint": False, "destructiveHint": writes}}


path = {"type": "string", "pattern": r"^Assets/Scripts/[A-Za-z0-9][A-Za-z0-9_.\-/]*\.cs$", "maxLength": 256}
entity = {"type": "string", "pattern": "^[1-9][0-9]*$"}
WEB_TOOLS.extend([
    script_tool("script_get_api", "Read verified TomCat C# APIs and a working movement example. Call before writing code; do not guess Unity APIs."),
    script_tool("script_list", "List project C# files, stable asset handles, classes, source_version and scene_version."),
    script_tool("script_read", "Read one C# source file and current versions.", {"path": path}, ["path"]),
    script_tool("script_write", "Create or update one project C# file (at most 48 KiB), preserving its asset handle. Source edits are checkpointed, not scene-undoable. Refuses stale versions or an unsaved human draft.", {"path": path, "text": {"type": "string", "maxLength": 49152}}, ["path", "text"], True),
    script_tool("script_compile", "Compile project scripts and return diagnostics. Check compilation.succeeded and restartRequired. When restartRequired is true, the user must rebuild via the C# panel before running updated code; never claim it is installed.", writes=True),
    script_tool("script_attach", "Attach a saved script to an entity, preserving other attachments and fields. Idempotent for the same asset. Read entity_get to verify.", {"path": path, "entity_id": entity}, ["path", "entity_id"], True),
    script_tool("script_detach", "Remove only the specified script attachment. Does not delete the source file. Get attachment_id from entity_get.script_attachments.", {"entity_id": entity, "attachment_id": entity}, ["entity_id", "attachment_id"], True),
])
BY_NAME = {tool["name"]: tool for tool in WEB_TOOLS}
