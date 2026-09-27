from __future__ import annotations

import json
from typing import Any, Iterator

from bg3loc.research.model import HANDLE_PATTERN, ResearchEvidence, ResearchMapping

RULE_DIALOG_NODE = "BG3-DIALOG-NODE-CONTEXT"


def traverse_dialog_json(
    dialog_data: dict[str, Any],
    *,
    resource_path: str = "",
    pak_name: str = ""
) -> Iterator[ResearchMapping]:
    """Traverse LSLib-converted dialog JSON (.lsj) and extract localization mappings."""
    save = dialog_data.get("save") or dialog_data
    regions = save.get("regions") or {}
    dialog = regions.get("dialog") or save

    dialog_uuid = ""
    uuid_field = dialog.get("UUID") or save.get("header", {}).get("uuid") or {}
    if isinstance(uuid_field, dict):
        dialog_uuid = str(uuid_field.get("value") or uuid_field.get("uuid") or "")
    elif uuid_field:
        dialog_uuid = str(uuid_field)

    nodes_raw = dialog.get("nodes") or save.get("nodes") or []
    if isinstance(nodes_raw, dict):
        nodes_raw = nodes_raw.get("node") or [nodes_raw]
    if not isinstance(nodes_raw, list):
        nodes_raw = [nodes_raw]

    node_list: list[dict[str, Any]] = []
    for item in nodes_raw:
        if isinstance(item, dict) and "node" in item:
            sub = item["node"]
            if isinstance(sub, list):
                node_list.extend(sub)
            else:
                node_list.append(sub)
        elif isinstance(item, dict):
            node_list.append(item)

    for node in node_list:
        if not isinstance(node, dict):
            continue
        u = node.get("UUID") or node.get("uuid")
        node_uuid = str(u.get("value") if isinstance(u, dict) else (u or ""))

        c = node.get("constructor") or node.get("type")
        node_type = str(c.get("value") if isinstance(c, dict) else (c or "DialogNode"))

        s = node.get("speaker") or node.get("Speaker")
        speaker_slot = str(s.get("value") if isinstance(s, dict) else (s or ""))

        handles: list[tuple[str, str]] = []

        def find_handles(obj: Any) -> None:
            if isinstance(obj, dict):
                h = obj.get("handle") or obj.get("Handle")
                if h:
                    v = obj.get("version") or obj.get("Version") or ""
                    handles.append((str(h), str(v)))
                for val in obj.values():
                    find_handles(val)
            elif isinstance(obj, list):
                for elem in obj:
                    find_handles(elem)

        tt = node.get("TaggedTexts") or node.get("taggedtexts")
        if tt:
            find_handles(tt)
        else:
            find_handles(node)

        for h_str, v_str in handles:
            m = HANDLE_PATTERN.search(h_str)
            if not m:
                continue

            uid = m.group("uid")
            ver = v_str or m.group("ver") or ""

            evidence = ResearchEvidence(
                sourceRole="DialogNodeTaggedText",
                resourcePath=resource_path,
                evidenceType="DialogGraph",
                ruleId=RULE_DIALOG_NODE,
                properties={
                    "dialogUuid": dialog_uuid,
                    "nodeUuid": node_uuid,
                    "nodeType": node_type,
                    "speakerSlot": speaker_slot,
                    "pakName": pak_name,
                }
            )

            yield ResearchMapping(
                contentUid=uid,
                mappingType="dialog-context",
                classification="DialogContextNode",
                evidence=[evidence],
                version=ver,
                metadata={
                    "dialogUuid": dialog_uuid,
                    "nodeUuid": node_uuid,
                    "speakerSlot": speaker_slot,
                }
            )