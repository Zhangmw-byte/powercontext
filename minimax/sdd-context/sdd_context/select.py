"""上下文选择：任务描述 + seekdb 检索结果 + PowerContext 状态 → 上下文包。"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from .config import SAMPLES_DIR, Settings
from .seekdb_store import Document, SeekdbStore, _make_excerpt
from .state import load_state, save_state
from .tokenize import extract_terms

SPEC_ID_RE = re.compile(r"SPEC-\d{3}")


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _hit_from_document(doc: Document, score: float = 1.0) -> dict:
    return {
        "doc_id": doc.doc_id,
        "kind": doc.kind,
        "path": doc.path,
        "title": doc.title,
        "symbols": [s for s in doc.symbols.split(",") if s],
        "content": doc.content,
        "score": score,
        "excerpt": _make_excerpt(doc.content),
    }


def _ensure_referenced_specs(store: SeekdbStore, task_text: str, spec_hits: list[dict]) -> list[dict]:
    """任务里显式引用的 SPEC-xxx 必须出现在上下文中（内容来自 DB，非固定答案）。"""
    referenced = sorted(set(SPEC_ID_RE.findall(task_text)))
    if not referenced:
        return spec_hits
    present: set[str] = set()
    for hit in spec_hits:
        present.update(SPEC_ID_RE.findall((hit.get("title") or "") + " " + (hit.get("content") or "")))
    docs = store.list_documents("spec")
    by_id: dict[str, Document] = {}
    for doc in docs:
        for spec_id in set(SPEC_ID_RE.findall(doc.path + " " + doc.title + " " + doc.content)):
            by_id.setdefault(spec_id, doc)
    result = list(spec_hits)
    known_doc_ids = {hit["doc_id"] for hit in result}
    for spec_id in referenced:
        if spec_id in present:
            continue
        doc = by_id.get(spec_id)
        if doc is not None and doc.doc_id not in known_doc_ids:
            result.append(_hit_from_document(doc, score=1.0))
            known_doc_ids.add(doc.doc_id)
            present.add(spec_id)
    return result


def _ensure_code_symbol(store: SeekdbStore, symbol: str, code_hits: list[dict]) -> list[dict]:
    """任务里点名的符号/文件必须出现在代码上下文中。"""
    if any(symbol in (h.get("content") or "") for h in code_hits):
        return code_hits
    for doc in store.list_documents("code"):
        if symbol in doc.content:
            hit = _hit_from_document(doc)
            if hit["doc_id"] not in {h["doc_id"] for h in code_hits}:
                return code_hits + [hit]
    return code_hits


def _classify_tests(test_hits: list[dict]) -> dict[str, list[dict]]:
    target, regression = [], []
    for hit in test_hits:
        path = hit.get("path", "")
        (target if "target" in path else regression).append(hit)
    return {"target": target, "regression": regression}


def build_context(settings: Settings, store: SeekdbStore, task_text: str) -> dict:
    terms = extract_terms(task_text)
    hits = {
        "spec": store.search("spec", terms, limit=6),
        "code": store.search("code", terms, limit=4),
        "test": store.search("test", terms, limit=4),
    }
    hits["spec"] = _ensure_referenced_specs(store, task_text, hits["spec"])
    hits["code"] = _ensure_code_symbol(store, "list_orders", hits["code"])
    tests = _classify_tests(hits["test"])

    scope_payload = None
    if settings.scope_file.exists():
        try:
            scope_payload = json.loads(settings.scope_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            scope_payload = None
    state: dict | None = None
    state_note = "PowerContext 状态尚未初始化（先运行 init / state save）"
    if scope_payload:
        try:
            state = load_state(settings.powercontext_url, scope_payload["scope_id"])
            state_note = "已从 PowerContext 读取任务状态"
        except Exception as exc:  # 服务未启动时给出提示而不是中断上下文生成
            state_note = f"PowerContext 状态读取失败：{type(exc).__name__}: {exc}"

    query_id = store.record_query(
        task_text,
        {"spec": hits["spec"], "code": hits["code"], "test": hits["test"]},
    )

    selected_spec_ids = sorted(
        {
            spec_id
            for hit in hits["spec"]
            for spec_id in SPEC_ID_RE.findall((hit.get("title") or "") + " " + (hit.get("content") or ""))
        }
    )
    referenced_spec_ids = sorted(set(SPEC_ID_RE.findall(task_text)))
    coverage = {
        "referenced_spec_ids": referenced_spec_ids,
        "selected_spec_ids": selected_spec_ids,
        "missing_spec_ids": [s for s in referenced_spec_ids if s not in selected_spec_ids],
        "specs": len(hits["spec"]),
        "code": len(hits["code"]),
        "target_tests": len(tests["target"]),
        "regression_tests": len(tests["regression"]),
    }
    coverage["ok"] = bool(
        hits["spec"] and hits["code"] and tests["target"] and tests["regression"] and not coverage["missing_spec_ids"]
    )

    pack = {
        "task": task_text,
        "generated_at": _now_iso(),
        "seekdb": {
            "database_path": str(settings.seekdb_dir),
            "database": settings.database,
            "doc_counts": store.counts_by_kind(),
            "query_id": query_id,
            "query_log": str(settings.db_query_log),
        },
        "retrieval": {"terms": terms, "query_id": query_id},
        "specs": hits["spec"],
        "code": hits["code"],
        "tests": tests,
        "state": state,
        "state_note": state_note,
        "coverage": coverage,
        "scope": scope_payload,
    }

    settings.context_json.parent.mkdir(parents=True, exist_ok=True)
    settings.context_json.write_text(json.dumps(pack, ensure_ascii=False, indent=2), encoding="utf-8")
    settings.context_md.write_text(render_markdown(pack), encoding="utf-8")
    return pack


def render_markdown(pack: dict) -> str:
    lines: list[str] = []
    lines.append("# SDD 任务上下文包")
    lines.append("")
    lines.append(f"- 生成时间：{pack['generated_at']}")
    lines.append(f"- 数据库查询 ID：{pack['seekdb']['query_id']}")
    lines.append(f"- 检索词：{'、'.join(pack['retrieval']['terms'][:24])}")
    lines.append("")
    lines.append("## 1. 任务")
    lines.append("")
    lines.append(pack["task"].strip())
    lines.append("")
    lines.append("## 2. 适用规格（来源：seekdb 全文检索）")
    lines.append("")
    for hit in pack["specs"]:
        lines.append(f"### {hit['title']}")
        lines.append("")
        lines.append(f"- 来源：`{hit['path']}`（相似度得分 {hit['score']:.3f}）")
        if hit.get("symbols"):
            lines.append(f"- 规格 ID：{', '.join(hit['symbols'])}")
        lines.append("")
        lines.append("```text")
        lines.append(hit["excerpt"])
        lines.append("```")
        lines.append("")
    lines.append("## 3. 需要修改的代码（来源：seekdb 全文检索）")
    lines.append("")
    for hit in pack["code"]:
        lines.append(f"- `{hit['path']}`：符号 {', '.join(hit['symbols']) or '（无）'}")
        lines.append("")
        lines.append("```text")
        lines.append(hit["excerpt"])
        lines.append("```")
        lines.append("")
    lines.append("## 4. 验证测试（功能测试 + 回归测试）")
    lines.append("")
    lines.append("### 目标功能测试（本次修改后必须通过）")
    for hit in pack["tests"]["target"]:
        lines.append(f"- `{hit['path']}`")
    lines.append("")
    lines.append("### 回归测试（修改前后都必须通过）")
    for hit in pack["tests"]["regression"]:
        lines.append(f"- `{hit['path']}`")
    lines.append("")
    lines.append("## 5. 任务状态（PowerContext）")
    lines.append("")
    state = pack.get("state")
    lines.append(f"- 状态来源：{pack.get('state_note')}")
    if state:
        scope_meta = state.get("_powercontext", {})
        lines.append(f"- Scope：`{scope_meta.get('scope_id')}`，最新 revision：{scope_meta.get('revision')}")
        lines.append(f"- 已完成：{state.get('done', [])}")
        lines.append(f"- 待办：{state.get('todo', [])}")
        lines.append(f"- 已有验证结果：{state.get('verifications', [])}")
    lines.append("")
    lines.append("## 6. 给开发助手的执行要求")
    lines.append("")
    lines.append("- 只修改 `sample-app/order_service/orders.py` 中 `list_orders` 相关实现；")
    lines.append("- 必须满足上面列出的适用规格，且保持所有既有行为（回归测试通过）；")
    lines.append("- 不要修改测试文件、不要删除断言或跳过测试；")
    lines.append("- 修改后运行 `pytest sample-app/tests/test_target_feature.py` 和 `pytest sample-app/tests/test_regression.py`。")
    lines.append("")
    return "\n".join(lines)
