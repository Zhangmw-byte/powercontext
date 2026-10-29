"""导入工程资料（规格 / 代码 / 测试）到 seekdb。"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .config import SAMPLES_DIR, SAMPLE_APP_DIR, Settings
from .seekdb_store import Document, SeekdbStore, _now_iso, _sha256

_DEF_CLASS = re.compile(r"^(?:class|def)\s+([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE)
_SPEC_ID = re.compile(r"SPEC-\d{3}")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _first_heading(text: str, default: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return default


def _symbols(text: str, fallback: str = "") -> str:
    found = _DEF_CLASS.findall(text)
    return ",".join(dict.fromkeys(found)) if found else fallback


def build_documents(settings: Settings) -> list[Document]:
    docs: list[Document] = []

    specs_dir = SAMPLES_DIR / "specs"
    for path in sorted(specs_dir.glob("*.md")):
        raw = _read(path)
        rel = path.relative_to(settings.minimax_dir).as_posix()
        title = _first_heading(raw, path.stem)
        doc_id = f"spec:{rel}"
        content = f"PATH: {rel}\nKIND: spec\nTITLE: {title}\n\n{raw}"
        docs.append(
            Document(
                doc_id=doc_id,
                kind="spec",
                path=rel,
                title=title,
                symbols=",".join(sorted(set(_SPEC_ID.findall(raw)))),
                content=content,
                content_sha=_sha256(content),
                updated_at=_now_iso(),
            )
        )

    for path in sorted((SAMPLE_APP_DIR / "order_service").glob("*.py")):
        raw = _read(path)
        rel = path.relative_to(settings.minimax_dir).as_posix()
        title = f"代码：{rel}"
        content = f"PATH: {rel}\nKIND: code\nSYMBOLS: {_symbols(raw)}\n\n{raw}"
        docs.append(
            Document(
                doc_id=f"code:{rel}",
                kind="code",
                path=rel,
                title=title,
                symbols=_symbols(raw),
                content=content,
                content_sha=_sha256(content),
                updated_at=_now_iso(),
            )
        )

    for path in sorted((SAMPLE_APP_DIR / "tests").glob("*.py")):
        raw = _read(path)
        rel = path.relative_to(settings.minimax_dir).as_posix()
        title = f"测试：{path.name}"
        content = f"PATH: {rel}\nKIND: test\nSYMBOLS: {_symbols(raw)}\n\n{raw}"
        docs.append(
            Document(
                doc_id=f"test:{rel}",
                kind="test",
                path=rel,
                title=title,
                symbols=_symbols(raw),
                content=content,
                content_sha=_sha256(content),
                updated_at=_now_iso(),
            )
        )

    return docs


def ingest(store: SeekdbStore, settings: Settings) -> dict:
    """全量导入（按 doc_id upsert，并删除已不存在的文档）。"""
    docs = build_documents(settings)
    inserted = store.upsert_documents(docs)
    for kind in ("spec", "code", "test"):
        store.delete_stale(kind, [d.doc_id for d in docs if d.kind == kind])

    summary = {
        "ts": _now_iso(),
        "documents": len(docs),
        "upserted": inserted,
        "by_kind": store.counts_by_kind(),
        "files": [
            {"doc_id": d.doc_id, "kind": d.kind, "path": d.path, "sha256": d.content_sha}
            for d in docs
        ],
    }
    settings.ingest_log.parent.mkdir(parents=True, exist_ok=True)
    with settings.ingest_log.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(summary, ensure_ascii=False) + "\n")
    return summary
