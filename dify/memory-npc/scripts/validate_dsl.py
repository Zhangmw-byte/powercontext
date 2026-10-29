#!/usr/bin/env python3
"""Validate workflows/memory-npc.yml against the REAL Dify 1.13.3 models.

Run inside the official api image (all dependencies present):
    docker run --rm --platform linux/amd64 \
        -v "$PWD:/work" -v "$HOME/dify-runtime-1.13.3/api:/dify-src:ro" \
        --entrypoint python langgenius/dify-api:1.13.3 /work/scripts/validate_dsl.py [path.yml]

Checks mirror services/app_dsl_service.py + dify_graph:
  * top-level keys, version must be str, kind app, mode workflow
  * graph.nodes non-empty; edges reference existing nodes; root is start
  * every node.data validated by the concrete dify_graph pydantic node model
"""

from __future__ import annotations

import sys

import yaml

sys.path.insert(0, "/app/api")

from dify_graph.nodes.code.entities import CodeNodeData  # noqa: E402
from dify_graph.nodes.end.entities import EndNodeData  # noqa: E402
from dify_graph.nodes.http_request.entities import HttpRequestNodeData  # noqa: E402
from dify_graph.nodes.if_else.entities import IfElseNodeData  # noqa: E402
from dify_graph.nodes.llm.entities import LLMNodeData  # noqa: E402
from dify_graph.nodes.start.entities import StartNodeData  # noqa: E402

MODELS = {
    "start": StartNodeData,
    "http-request": HttpRequestNodeData,
    "code": CodeNodeData,
    "llm": LLMNodeData,
    "if-else": IfElseNodeData,
    "end": EndNodeData,
}


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else "/work/workflows/memory-npc.yml"
    data = yaml.safe_load(open(path, encoding="utf-8"))
    failures: list[str] = []

    version = data.get("version")
    if not isinstance(version, str):
        failures.append(f"version must be str, got {type(version).__name__}")
    if data.get("kind") != "app":
        failures.append("kind must be 'app'")
    app = data.get("app") or {}
    if app.get("mode") != "workflow":
        failures.append("app.mode must be 'workflow'")
    if not app.get("name"):
        failures.append("app.name missing")

    workflow = data.get("workflow")
    if not isinstance(workflow, dict):
        print("FAIL:", "; ".join(failures))
        return 1
    graph = workflow.get("graph") or {}
    nodes = graph.get("nodes") or []
    edges = graph.get("edges") or []
    if not nodes:
        failures.append("graph.nodes empty")

    node_ids = {str(n.get("id")) for n in nodes}
    executable = [n for n in nodes if (n.get("data") or {}).get("type") != "custom-note"]
    root_types = {"start", "datasource", "trigger-schedule", "trigger-webhook", "trigger-plugin"}
    roots = [n for n in executable if (n.get("data") or {}).get("type") in root_types]
    if not roots:
        failures.append("no root (start/trigger) node")
    else:
        print(f"root node: {roots[0]['id']} ({roots[0]['data']['type']})")

    for n in nodes:
        ndata = n.get("data") or {}
        ntype = ndata.get("type")
        model = MODELS.get(ntype)
        if model is None:
            failures.append(f"node {n.get('id')}: unknown data type {ntype!r}")
            continue
        try:
            model.model_validate(ndata)
            print(f"PASS {n['id']:24} {ntype}")
        except Exception as error:  # noqa: BLE001
            failures.append(f"node {n.get('id')} ({ntype}): {error}")

    for e in edges:
        src, dst = e.get("source"), e.get("target")
        if src not in node_ids or dst not in node_ids:
            failures.append(f"edge {e.get('id')}: references missing node {src}->{dst}")

    if_edges = {(e.get("source"), str(e.get("sourceHandle"))) for e in edges}
    for n in nodes:
        ndata = n.get("data") or {}
        if ndata.get("type") == "if-else":
            for case in ndata.get("cases") or []:
                handle = str(case.get("case_id"))
                if (n["id"], handle) not in if_edges:
                    failures.append(f"if-else {n['id']}: no edge for case handle {handle!r}")
            if (n["id"], "false") not in if_edges:
                failures.append(f"if-else {n['id']}: no else(false) edge")

    if failures:
        print("\nFAILURES:")
        for f in failures:
            print(" -", f)
        return 1
    print(f"\nOK: {len(nodes)} nodes, {len(edges)} edges validated against Dify 1.13.3 dify_graph models")
    return 0


if __name__ == "__main__":
    sys.exit(main())
