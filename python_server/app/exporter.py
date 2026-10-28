"""每日 CSV 导出：按 AI 热度分排序，热词以 JSON 数组字符串输出。"""

from __future__ import annotations

import csv
import json
import logging
import os
import sqlite3
from pathlib import Path

from .config import Config
from .db import Database
from .sources import SOURCE_LABELS

logger = logging.getLogger(__name__)

CSV_HEADERS = [
    "抓取时间",
    "来源",
    "原标题",
    "热词",
    "AI热度分",
    "评分理由",
    "简介",
    "分类",
    "榜单排名",
    "平台热度",
    "链接",
    "发布时间",
]


def _value(row: sqlite3.Row, key: str) -> object:
    try:
        value = row[key]
    except (IndexError, KeyError):
        return ""
    return "" if value is None else value


def _hot_words_json(raw: object) -> str:
    if not raw:
        return "[]"
    try:
        words = json.loads(str(raw))
    except (TypeError, ValueError):
        return "[]"
    if not isinstance(words, list):
        return "[]"
    return json.dumps([str(word) for word in words], ensure_ascii=False)


def export_path(config: Config, day: str) -> Path:
    return config.export_dir / f"{day}_hotspots.csv"


def export_day(db: Database, config: Config, day: str) -> Path:
    """生成/刷新指定日期的 CSV，返回文件路径。"""
    config.export_dir.mkdir(parents=True, exist_ok=True)
    rows = db.items_for_day(day)
    path = export_path(config, day)
    tmp_path = path.with_name(path.name + ".tmp")

    try:
        with tmp_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(CSV_HEADERS)
            for row in rows:
                writer.writerow(
                    [
                        _value(row, "fetched_at"),
                        SOURCE_LABELS.get(str(row["source"]), str(row["source"])),
                        _value(row, "title"),
                        _hot_words_json(_value(row, "hot_words")),
                        _value(row, "ai_score"),
                        _value(row, "ai_reason"),
                        _value(row, "ai_summary"),
                        _value(row, "ai_category"),
                        _value(row, "rank"),
                        _value(row, "raw_heat"),
                        _value(row, "url"),
                        _value(row, "published_at"),
                    ]
                )
        os.replace(tmp_path, path)
    except PermissionError:
        logger.warning(
            "CSV 写入失败：文件可能正在 Excel 中打开，已保留旧文件。路径：%s", path
        )
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        return path
    except Exception:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise

    logger.info("已导出 CSV：%s（%s 条）", path, len(rows))
    return path
