"""SQLite 状态库：标题去重、AI 结果缓存、运行记录。"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Sequence

from .models import Analysis, RawItem

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    source            TEXT NOT NULL,
    source_id         TEXT,
    title             TEXT NOT NULL,
    title_hash        TEXT NOT NULL UNIQUE,
    url               TEXT NOT NULL,
    rank              INTEGER,
    raw_heat          INTEGER,
    published_at      TEXT,
    extra             TEXT,
    first_seen_at     TEXT NOT NULL,
    fetched_at        TEXT NOT NULL,
    last_seen_at      TEXT NOT NULL,
    seen_count        INTEGER NOT NULL DEFAULT 1,
    hot_words         TEXT,
    ai_score          INTEGER,
    ai_reason         TEXT,
    ai_summary        TEXT,
    ai_category       TEXT,
    ai_junk           INTEGER,
    ai_model          TEXT,
    analyzed_at       TEXT,
    analyze_attempts  INTEGER NOT NULL DEFAULT 0,
    last_error        TEXT
);

CREATE INDEX IF NOT EXISTS idx_items_fetched_at ON items(fetched_at);
CREATE INDEX IF NOT EXISTS idx_items_pending
    ON items(analyzed_at) WHERE analyzed_at IS NULL;

CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    status      TEXT NOT NULL,
    sources     TEXT,
    fetched     INTEGER NOT NULL DEFAULT 0,
    new_items   INTEGER NOT NULL DEFAULT 0,
    analyzed    INTEGER NOT NULL DEFAULT 0,
    message     TEXT
);
"""


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.conn: sqlite3.Connection | None = None

    # ------------------------------------------------------------------ 基础
    def connect(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, timeout=30)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.execute("PRAGMA busy_timeout=10000")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        if self.conn is not None:
            self.conn.close()
            self.conn = None

    @property
    def c(self) -> sqlite3.Connection:
        if self.conn is None:
            raise RuntimeError("Database.connect() 尚未调用")
        return self.conn

    # ------------------------------------------------------------------ 条目
    def upsert_item(self, item: RawItem, seen_at: str) -> tuple[int, bool]:
        """插入新条目，或刷新已存在条目的最新抓取时间/次数。

        返回 (item_id, is_new)。相同 title_hash 只保留一行，永不重复分析。
        """
        existing = self.c.execute(
            "SELECT id FROM items WHERE title_hash = ?", (item.title_hash,)
        ).fetchone()

        if existing:
            item_id = int(existing["id"])
            self.c.execute(
                """
                UPDATE items
                SET last_seen_at = ?,
                    fetched_at = ?,
                    seen_count = seen_count + 1,
                    rank = ?,
                    raw_heat = ?,
                    url = ?,
                    source_id = COALESCE(?, source_id),
                    published_at = COALESCE(?, published_at),
                    extra = ?
                WHERE id = ?
                """,
                (
                    seen_at,
                    seen_at,
                    item.rank,
                    item.raw_heat,
                    item.url,
                    item.source_id,
                    item.published_at,
                    json.dumps(item.extra, ensure_ascii=False) if item.extra else None,
                    item_id,
                ),
            )
            self.c.commit()
            return item_id, False

        cursor = self.c.execute(
            """
            INSERT INTO items (
                source, source_id, title, title_hash, url, rank, raw_heat,
                published_at, extra, first_seen_at, fetched_at, last_seen_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item.source,
                item.source_id,
                item.title,
                item.title_hash,
                item.url,
                item.rank,
                item.raw_heat,
                item.published_at,
                json.dumps(item.extra, ensure_ascii=False) if item.extra else None,
                seen_at,
                seen_at,
                seen_at,
            ),
        )
        self.c.commit()
        return int(cursor.lastrowid), True

    def pending_items(self, day: str, limit: int = 500, max_attempts: int = 3) -> list[sqlite3.Row]:
        return list(
            self.c.execute(
                """
                SELECT * FROM items
                WHERE analyzed_at IS NULL
                  AND analyze_attempts < ?
                  AND substr(fetched_at, 1, 10) = ?
                ORDER BY fetched_at ASC, id ASC
                LIMIT ?
                """,
                (max_attempts, day, limit),
            ).fetchall()
        )

    def save_analysis(self, item_id: int, analysis: Analysis, model: str, analyzed_at: str) -> None:
        self.c.execute(
            """
            UPDATE items
            SET hot_words = ?,
                ai_score = ?,
                ai_reason = ?,
                ai_summary = ?,
                ai_category = ?,
                ai_junk = ?,
                ai_model = ?,
                analyzed_at = ?,
                last_error = NULL
            WHERE id = ?
            """,
            (
                json.dumps(analysis.hot_words, ensure_ascii=False),
                analysis.score,
                analysis.reason,
                analysis.summary,
                analysis.category,
                1 if analysis.is_junk else 0,
                model,
                analyzed_at,
                item_id,
            ),
        )
        self.c.commit()

    def mark_attempt(self, item_ids: Sequence[int], error: str) -> None:
        if not item_ids:
            return
        self.c.executemany(
            """
            UPDATE items
            SET analyze_attempts = analyze_attempts + 1,
                last_error = ?
            WHERE id = ?
            """,
            [(error[:1000], item_id) for item_id in item_ids],
        )
        self.c.commit()

    def items_for_day(self, day: str) -> list[sqlite3.Row]:
        """当天 CSV 的数据源：按 AI 热度分降序，未分析的排最后。"""
        return list(
            self.c.execute(
                """
                SELECT * FROM items
                WHERE substr(fetched_at, 1, 10) = ?
                ORDER BY CASE WHEN ai_score IS NULL THEN 1 ELSE 0 END,
                         ai_score DESC,
                         fetched_at DESC,
                         id DESC
                """,
                (day,),
            ).fetchall()
        )

    def count_for_day(self, day: str) -> int:
        row = self.c.execute(
            "SELECT COUNT(*) AS n FROM items WHERE substr(fetched_at, 1, 10) = ?",
            (day,),
        ).fetchone()
        return int(row["n"]) if row else 0

    # ------------------------------------------------------------------ 运行记录
    def start_run(self, started_at: str, sources: Sequence[str]) -> int:
        cursor = self.c.execute(
            "INSERT INTO runs (started_at, status, sources) VALUES (?, 'running', ?)",
            (started_at, ",".join(sources)),
        )
        self.c.commit()
        return int(cursor.lastrowid)

    def finish_run(
        self,
        run_id: int,
        *,
        status: str,
        fetched: int,
        new_items: int,
        analyzed: int,
        message: str = "",
        finished_at: str,
    ) -> None:
        self.c.execute(
            """
            UPDATE runs
            SET finished_at = ?, status = ?, fetched = ?, new_items = ?,
                analyzed = ?, message = ?
            WHERE id = ?
            """,
            (finished_at, status, fetched, new_items, analyzed, message[:2000], run_id),
        )
        self.c.commit()

    def recent_runs(self, limit: int = 10) -> list[sqlite3.Row]:
        return list(
            self.c.execute(
                "SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        )
