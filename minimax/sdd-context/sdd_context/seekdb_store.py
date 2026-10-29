"""seekdb 存储层：工程资料（规格 / 代码 / 测试）的落库与全文检索。

实现说明：
- 使用 pyseekdb 的 embedded 模式（pip 包 + pylibseekdb 本地库），不需要单独启动服务；
- 通过 pyseekdb 暴露的底层连接执行 MySQL 兼容 SQL（seekdb 即 MySQL 兼容），
  表上建立 ``FULLTEXT ... WITH PARSER ik`` 全文索引，检索用 ``MATCH ... AGAINST``；
- 选型原因：上下文选择需要“按任务描述检索工程资料”，全文索引比外部向量模型更轻、
  在干净环境可复现（无需下载 embedding 模型、无需网络）。
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pyseekdb
from pymysql.converters import escape_string

from .tokenize import match_query


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sql_str(value: Any) -> str:
    """把 Python 值转成 SQL 字符串字面量（含引号）。"""
    if value is None:
        return "NULL"
    return "'" + escape_string(str(value)) + "'"


@dataclass(frozen=True)
class Document:
    doc_id: str
    kind: str  # spec / code / test
    path: str
    title: str
    symbols: str
    content: str
    content_sha: str
    updated_at: str


_SCHEMA_SQL = [
    """
    CREATE TABLE IF NOT EXISTS sdd_documents (
      doc_id VARCHAR(191) NOT NULL PRIMARY KEY,
      kind VARCHAR(16) NOT NULL,
      path VARCHAR(512) NOT NULL,
      title VARCHAR(255) NOT NULL DEFAULT '',
      symbols VARCHAR(512) NOT NULL DEFAULT '',
      content MEDIUMTEXT NOT NULL,
      content_sha VARCHAR(64) NOT NULL,
      updated_at VARCHAR(40) NOT NULL,
      FULLTEXT INDEX ft_sdd_documents_content (content) WITH PARSER ik
    ) DEFAULT CHARSET = utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS sdd_queries (
      query_id VARCHAR(80) NOT NULL PRIMARY KEY,
      task MEDIUMTEXT NOT NULL,
      created_at VARCHAR(40) NOT NULL,
      hits_json MEDIUMTEXT NOT NULL
    ) DEFAULT CHARSET = utf8mb4
    """,
]


class SeekdbStore:
    """seekdb（embedded）上的工程资料仓库。"""

    def __init__(self, db_path: Path | str, database: str = "sdd", query_log: Path | None = None) -> None:
        self.db_path = Path(db_path)
        self.database = database
        self.query_log = Path(query_log) if query_log else None
        self.db_path.mkdir(parents=True, exist_ok=True)
        self._admin = pyseekdb.AdminClient(path=str(self.db_path))
        self._ensure_database()
        self.client = pyseekdb.Client(path=str(self.db_path), database=self.database)
        # pyseekdb 的 Client 代理只暴露 collection 操作；这里需要执行 SQL，
        # 因此使用它内部的底层连接（版本固定见 requirements.txt）。
        self._conn = self.client._server  # noqa: SLF001 - pyseekdb 未公开 SQL 入口
        self.ensure_schema()

    # ------------------------------------------------------------------ 基础
    def _ensure_database(self) -> None:
        names = [getattr(db, "name", str(db)) for db in self._admin.list_databases()]
        if self.database not in names:
            self._admin.create_database(self.database)

    def execute(self, sql: str, log: bool = True) -> list[Any]:
        started = time.time()
        rows = self._conn._execute(sql)  # noqa: SLF001 - 同上
        if log and self.query_log is not None:
            self._log_sql(sql, rows, (time.time() - started) * 1000)
        return rows if rows is not None else []

    def _log_sql(self, sql: str, rows: Any, elapsed_ms: float) -> None:
        if self.query_log is None:
            return
        self.query_log.parent.mkdir(parents=True, exist_ok=True)
        try:
            row_count = len(rows) if rows else 0
        except TypeError:
            row_count = 0
        snippet = " ".join(sql.split())
        if len(snippet) > 2000:
            snippet = snippet[:2000] + "..."
        with self.query_log.open("a", encoding="utf-8") as fh:
            fh.write(
                json.dumps(
                    {
                        "ts": _now_iso(),
                        "elapsed_ms": round(elapsed_ms, 2),
                        "rows": row_count,
                        "sql": snippet,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )

    def ensure_schema(self) -> None:
        for statement in _SCHEMA_SQL:
            self.execute(statement, log=False)

    # ------------------------------------------------------------------ 写入
    def upsert_documents(self, documents: Iterable[Document]) -> int:
        count = 0
        for doc in documents:
            self.execute(
                "REPLACE INTO sdd_documents "
                "(doc_id, kind, path, title, symbols, content, content_sha, updated_at) VALUES ("
                + ", ".join(
                    [
                        sql_str(doc.doc_id),
                        sql_str(doc.kind),
                        sql_str(doc.path),
                        sql_str(doc.title),
                        sql_str(doc.symbols),
                        sql_str(doc.content),
                        sql_str(doc.content_sha),
                        sql_str(doc.updated_at),
                    ]
                )
                + ")"
            )
            count += 1
        return count

    def delete_stale(self, kind: str, keep_ids: Iterable[str]) -> int:
        keep = sorted({str(i) for i in keep_ids})
        if not keep:
            self.execute(f"DELETE FROM sdd_documents WHERE kind = {sql_str(kind)}")
            return 0
        quoted = ", ".join(sql_str(i) for i in keep)
        rows = self.execute(f"SELECT doc_id FROM sdd_documents WHERE kind = {sql_str(kind)}")
        stale = [row[0] for row in rows if row[0] not in set(keep)]
        for doc_id in stale:
            self.execute(f"DELETE FROM sdd_documents WHERE doc_id = {sql_str(doc_id)}")
        return len(stale)

    # ------------------------------------------------------------------ 读取
    def get_document(self, doc_id: str) -> Document | None:
        rows = self.execute(
            "SELECT doc_id, kind, path, title, symbols, content, content_sha, updated_at "
            f"FROM sdd_documents WHERE doc_id = {sql_str(doc_id)}"
        )
        if not rows:
            return None
        return self._row_to_document(rows[0])

    def list_documents(self, kind: str | None = None) -> list[Document]:
        where = f" WHERE kind = {sql_str(kind)}" if kind else ""
        rows = self.execute(
            "SELECT doc_id, kind, path, title, symbols, content, content_sha, updated_at "
            f"FROM sdd_documents{where} ORDER BY kind, path"
        )
        return [self._row_to_document(row) for row in rows]

    def counts_by_kind(self) -> dict[str, int]:
        rows = self.execute("SELECT kind, COUNT(*) FROM sdd_documents GROUP BY kind")
        return {row[0]: int(row[1]) for row in rows}

    def search(self, kind: str, terms: list[str], limit: int = 6) -> list[dict]:
        """FULLTEXT 检索 + LIKE 兜底；返回带 score/excerpt 的结果。"""
        if not terms:
            return []
        query = match_query(terms)
        results: list[dict] = []
        if query:
            sql = (
                "SELECT doc_id, path, title, symbols, content, "
                "MATCH(content) AGAINST(" + sql_str(query) + " IN NATURAL LANGUAGE MODE) AS score "
                f"FROM sdd_documents WHERE kind = {sql_str(kind)} "
                "AND MATCH(content) AGAINST(" + sql_str(query) + " IN NATURAL LANGUAGE MODE) "
                f"ORDER BY score DESC LIMIT {int(limit)}"
            )
            rows = self.execute(sql)
            results = [self._hit(row, 4) for row in rows]

        if len(results) < limit:
            like_terms = [t for t in terms[:10] if t]
            conditions = " OR ".join(
                [f"content LIKE {sql_str('%' + t + '%')}" for t in like_terms]
            )
            if conditions:
                rows = self.execute(
                    "SELECT doc_id, path, title, symbols, content "
                    f"FROM sdd_documents WHERE kind = {sql_str(kind)} AND ({conditions}) "
                    f"LIMIT {int(limit * 2)}"
                )
                known = {r["doc_id"] for r in results}
                for row in rows:
                    if row[0] in known:
                        continue
                    hit = self._hit(row, 0.0)
                    hit["score"] = self._keyword_score(hit, terms)
                    results.append(hit)
                    known.add(row[0])
        results.sort(key=lambda item: item["score"], reverse=True)
        return results[:limit]

    def record_query(self, task: str, hits: dict[str, list[dict]]) -> str:
        query_id = f"q-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"
        summary = {
            "specs": [h["doc_id"] for h in hits.get("spec", [])],
            "code": [h["doc_id"] for h in hits.get("code", [])],
            "tests": [h["doc_id"] for h in hits.get("test", [])],
        }
        self.execute(
            "REPLACE INTO sdd_queries (query_id, task, created_at, hits_json) VALUES ("
            + ", ".join(
                [
                    sql_str(query_id),
                    sql_str(task[:4000]),
                    sql_str(_now_iso()),
                    sql_str(json.dumps(summary, ensure_ascii=False)),
                ]
            )
            + ")"
        )
        return query_id

    def recent_queries(self, limit: int = 5) -> list[dict]:
        rows = self.execute(
            "SELECT query_id, task, created_at, hits_json FROM sdd_queries "
            f"ORDER BY created_at DESC LIMIT {int(limit)}"
        )
        return [
            {
                "query_id": row[0],
                "task": row[1],
                "created_at": row[2],
                "hits": json.loads(row[3]) if row[3] else {},
            }
            for row in rows
        ]

    # ------------------------------------------------------------------ 工具
    @staticmethod
    def _row_to_document(row: Any) -> Document:
        return Document(
            doc_id=row[0],
            kind=row[1],
            path=row[2],
            title=row[3],
            symbols=row[4],
            content=row[5],
            content_sha=row[6],
            updated_at=row[7],
        )

    @staticmethod
    def _hit(row: Any, score: float) -> dict:
        content = row[4] or ""
        return {
            "doc_id": row[0],
            "path": row[1],
            "title": row[2],
            "symbols": [s for s in (row[3] or "").split(",") if s],
            "content": content,
            "score": float(score or 0.0),
            "excerpt": _make_excerpt(content),
        }

    @staticmethod
    def _keyword_score(hit: dict, terms: list[str]) -> float:
        text = (hit.get("content") or "") + "\n" + (hit.get("title") or "")
        hits = sum(1 for term in terms if term and term in text)
        return float(hits) / max(1, len(terms))


def _make_excerpt(content: str, max_lines: int = 6, max_chars: int = 700) -> str:
    """取文档中信息量较高的若干行作为摘录。"""
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    picked: list[str] = []
    in_frontmatter = False
    for line in lines:
        if line == "---":
            in_frontmatter = not in_frontmatter
            continue
        if in_frontmatter:
            continue
        if line.startswith(("PATH:", "KIND:", "TITLE:", "SYMBOLS:")):
            continue
        picked.append(line)
        if sum(len(x) for x in picked) >= max_chars or len(picked) >= max_lines:
            break
    text = "\n".join(picked)
    return text[:max_chars]
