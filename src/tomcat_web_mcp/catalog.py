from copy import deepcopy
from tomcat_skills.tools import TOOLS

# Do not advertise capabilities that the Web host cannot execute with the same semantics.
UNSUPPORTED = {"scene_save", "console_get_entries", "editor_step"}
WEB_TOOLS = [deepcopy(tool) for tool in TOOLS if tool["name"] not in UNSUPPORTED]
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
