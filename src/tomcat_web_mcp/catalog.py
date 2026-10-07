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
BY_NAME = {tool["name"]: tool for tool in WEB_TOOLS}
