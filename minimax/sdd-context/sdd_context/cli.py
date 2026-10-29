"""命令行入口：init / ingest / context / state-* / doctor / verify。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import SAMPLES_DIR, ensure_runtime, settings
from .ingest import ingest
from .seekdb_store import SeekdbStore
from .select import build_context
from .state import ensure_scope, load_state, record_test_result, save_state, update_state_fields


def _store(args: argparse.Namespace) -> tuple:
    cfg = settings(args.runtime, args.powercontext_url)
    ensure_runtime(cfg)
    return cfg, SeekdbStore(cfg.seekdb_dir, cfg.database, cfg.db_query_log)


def cmd_init(args: argparse.Namespace) -> int:
    cfg, store = _store(args)
    scope = ensure_scope(cfg.powercontext_url, cfg.scope_file, fresh=args.fresh)
    print(json.dumps({"runtime": str(cfg.runtime_dir), "scope": scope, "doc_counts": store.counts_by_kind()}, ensure_ascii=False, indent=2))
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    cfg, store = _store(args)
    summary = ingest(store, cfg)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def cmd_context(args: argparse.Namespace) -> int:
    cfg, store = _store(args)
    task_file = Path(args.task_file) if args.task_file else SAMPLES_DIR / "task.md"
    task_text = task_file.read_text(encoding="utf-8")
    pack = build_context(cfg, store, task_text)
    print(json.dumps({"context_json": str(cfg.context_json), "context_md": str(cfg.context_md), "coverage": pack["coverage"]}, ensure_ascii=False, indent=2))
    return 0 if pack["coverage"]["ok"] else 2


def cmd_state_show(args: argparse.Namespace) -> int:
    cfg = settings(args.runtime, args.powercontext_url)
    if not cfg.scope_file.exists():
        print(json.dumps({"error": "scope not initialized"}, ensure_ascii=False))
        return 2
    scope = json.loads(cfg.scope_file.read_text(encoding="utf-8"))
    state = load_state(cfg.powercontext_url, scope["scope_id"])
    print(json.dumps({"scope": scope, "state": state}, ensure_ascii=False, indent=2))
    return 0 if state else 2


def cmd_state_save(args: argparse.Namespace) -> int:
    cfg = settings(args.runtime, args.powercontext_url)
    if not cfg.scope_file.exists():
        print(json.dumps({"error": "scope not initialized; run init first"}, ensure_ascii=False))
        return 2
    scope = json.loads(cfg.scope_file.read_text(encoding="utf-8"))
    state = json.loads(Path(args.file).read_text(encoding="utf-8"))
    saved = save_state(cfg.powercontext_url, scope["scope_id"], state)
    print(json.dumps({"scope_id": scope["scope_id"], "saved": saved, "state": state}, ensure_ascii=False, indent=2))
    return 0


def cmd_state_record_test(args: argparse.Namespace) -> int:
    cfg = settings(args.runtime, args.powercontext_url)
    scope = json.loads(cfg.scope_file.read_text(encoding="utf-8"))
    state = record_test_result(
        cfg.powercontext_url,
        scope["scope_id"],
        name=args.name,
        command=args.command,
        exit_code=args.exit_code,
        passed=bool(args.passed),
        code_sha=args.code_sha,
    )
    print(json.dumps(state, ensure_ascii=False, indent=2))
    return 0


def cmd_state_finalize(args: argparse.Namespace) -> int:
    cfg = settings(args.runtime, args.powercontext_url)
    scope = json.loads(cfg.scope_file.read_text(encoding="utf-8"))
    state = update_state_fields(
        cfg.powercontext_url,
        scope["scope_id"],
        task=args.task,
        done=args.done or None,
        todo=args.todo or None,
    )
    print(json.dumps(state, ensure_ascii=False, indent=2))
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    cfg, store = _store(args)
    info = {
        "minimax_dir": str(cfg.minimax_dir),
        "runtime_dir": str(cfg.runtime_dir),
        "seekdb_dir": str(cfg.seekdb_dir),
        "database": cfg.database,
        "doc_counts": store.counts_by_kind(),
        "documents": [
            {"doc_id": d.doc_id, "kind": d.kind, "path": d.path, "sha256": d.content_sha}
            for d in store.list_documents()
        ],
        "powercontext_url": cfg.powercontext_url,
        "scope": json.loads(cfg.scope_file.read_text(encoding="utf-8")) if cfg.scope_file.exists() else None,
        "recent_queries": store.recent_queries(5),
    }
    print(json.dumps(info, ensure_ascii=False, indent=2))
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    cfg, store = _store(args)
    task_file = Path(args.task_file) if args.task_file else SAMPLES_DIR / "task.md"
    pack = build_context(cfg, store, task_file.read_text(encoding="utf-8"))
    coverage = pack["coverage"]
    print(json.dumps(coverage, ensure_ascii=False, indent=2))
    return 0 if coverage["ok"] else 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sdd-context", description="SDD 上下文模块 CLI")
    parser.add_argument("--runtime", default=None, help="运行时目录（默认 minimax/.runtime）")
    parser.add_argument("--powercontext-url", default=None, help="PowerContext Server 地址（默认 env 或 http://127.0.0.1:18080）")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help="初始化运行时目录、seekdb 库表、PowerContext Scope")
    p.add_argument("--fresh", action="store_true", help="强制新建 PowerContext Scope")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("ingest", help="把规格/代码/测试导入 seekdb")
    p.set_defaults(func=cmd_ingest)

    p = sub.add_parser("context", help="按任务描述检索并生成上下文包")
    p.add_argument("--task-file", default=None, help="任务描述文件（默认 sample-task/task.md）")
    p.set_defaults(func=cmd_context)

    p = sub.add_parser("state-show", help="读取 PowerContext 中的任务状态")
    p.set_defaults(func=cmd_state_show)

    p = sub.add_parser("state-save", help="把 JSON 状态写入 PowerContext")
    p.add_argument("--file", required=True)
    p.set_defaults(func=cmd_state_save)

    p = sub.add_parser("state-record-test", help="把一次测试结果写入 PowerContext 状态")
    p.add_argument("--name", required=True)
    p.add_argument("--command", required=True)
    p.add_argument("--exit-code", type=int, required=True)
    p.add_argument("--passed", type=int, choices=[0, 1], required=True)
    p.add_argument("--code-sha", default="")
    p.set_defaults(func=cmd_state_record_test)


    p = sub.add_parser("state-finalize", help="更新已完成/待办并保留验证结果")
    p.add_argument("--task", default=None)
    p.add_argument("--done", action="append", default=[])
    p.add_argument("--todo", action="append", default=[])
    p.set_defaults(func=cmd_state_finalize)

    p = sub.add_parser("doctor", help="打印运行环境、数据库文档、scope 与查询记录")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("verify", help="校验上下文覆盖是否满足任务要求")
    p.add_argument("--task-file", default=None)
    p.set_defaults(func=cmd_verify)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except Exception as exc:  # 给命令行用户一个可读错误
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
