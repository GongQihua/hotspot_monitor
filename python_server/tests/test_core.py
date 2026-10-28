"""核心逻辑单元测试（不访问网络、不调用 AI）。"""

from __future__ import annotations

import csv
import shutil
import sys
import unittest
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from app.ai import parse_analysis_payload  # noqa: E402
from app.db import Database  # noqa: E402
from app.exporter import CSV_HEADERS, export_day  # noqa: E402
from app.models import Analysis, RawItem  # noqa: E402
from app.scheduler import next_run_at  # noqa: E402
from app.utils import normalize_title, parse_heat  # noqa: E402


class DummyConfig:
    def __init__(self, export_dir: Path):
        self.export_dir = export_dir


class UtilsTests(unittest.TestCase):
    def test_normalize_title_variants(self):
        self.assertEqual(normalize_title("＃雷军# 回应"), normalize_title("#雷军#回应"))
        self.assertEqual(normalize_title("iPhone 17 发布！"), normalize_title("iPhone17发布"))
        self.assertEqual(normalize_title("A-B_C"), normalize_title("abc"))

    def test_normalize_title_keeps_different_titles(self):
        self.assertNotEqual(normalize_title("雷军回应"), normalize_title("小米回应"))

    def test_parse_heat(self):
        self.assertEqual(parse_heat("523 万热度"), 5_230_000)
        self.assertEqual(parse_heat("1.2亿"), 120_000_000)
        self.assertEqual(parse_heat("1234567"), 1_234_567)
        self.assertIsNone(parse_heat("暂无"))


class DatabaseExportTests(unittest.TestCase):
    def setUp(self):
        # 不用 tempfile：DSH 沙箱下 tempfile 创建的目录 ACL 会拒绝写入
        self.root = BASE_DIR / "data" / "_test" / self._testMethodName
        if self.root.exists():
            shutil.rmtree(self.root, ignore_errors=True)
        self.root.mkdir(parents=True)
        self.db = Database(self.root / "test.db")
        self.db.connect()
        self.cfg = DummyConfig(self.root / "exports")

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.root, ignore_errors=True)

    def test_dedupe_updates_time_and_seen_count(self):
        first = RawItem(
            source="weibo",
            title="雷军回应小米SU7交付",
            url="https://example.com/1",
            rank=1,
            raw_heat=100,
        )
        item_id, is_new = self.db.upsert_item(first, "2026-10-28 08:00:00")
        self.assertTrue(is_new)

        second = RawItem(
            source="weibo",
            title="雷军回应小米SU7交付！",
            url="https://example.com/1",
            rank=2,
            raw_heat=200,
        )
        same_id, is_new = self.db.upsert_item(second, "2026-10-28 16:00:00")
        self.assertFalse(is_new)
        self.assertEqual(item_id, same_id)

        row = self.db.c.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
        self.assertEqual(row["seen_count"], 2)
        self.assertEqual(row["first_seen_at"], "2026-10-28 08:00:00")
        self.assertEqual(row["fetched_at"], "2026-10-28 16:00:00")
        self.assertEqual(row["rank"], 2)

    def test_export_sorted_by_ai_score_with_null_last(self):
        high = RawItem("weibo", "高分标题", "https://example.com/high", rank=1)
        low = RawItem("zhihu", "低分标题", "https://example.com/low", rank=2)
        pending = RawItem("bilibili", "未分析标题", "https://example.com/pending", rank=3)

        high_id, _ = self.db.upsert_item(high, "2026-10-28 08:00:00")
        self.db.upsert_item(low, "2026-10-28 09:00:00")
        self.db.upsert_item(pending, "2026-10-28 10:00:00")

        self.db.save_analysis(
            high_id,
            Analysis(
                hot_words=["雷军", "小米SU7"],
                score=88,
                reason="头部人物+交付节点",
                summary="小米SU7交付突破20万辆",
                category="科技",
            ),
            "deepseek-chat",
            "2026-10-28 08:01:00",
        )
        low_id = self.db.c.execute(
            "SELECT id FROM items WHERE title = ?", ("低分标题",)
        ).fetchone()["id"]
        self.db.save_analysis(
            low_id,
            Analysis(["测试"], 42, "普通话题", "一条普通话题", "其他"),
            "deepseek-chat",
            "2026-10-28 09:01:00",
        )

        path = export_day(self.db, self.cfg, "2026-10-28")
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.reader(handle))

        self.assertEqual(rows[0], CSV_HEADERS)
        self.assertEqual([row[2] for row in rows[1:]], ["高分标题", "低分标题", "未分析标题"])
        self.assertEqual(rows[1][4], "88")
        self.assertEqual(rows[1][3], '["雷军", "小米SU7"]')
        self.assertEqual(rows[3][4], "")

        raw = path.read_bytes()
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"), "CSV 应带 UTF-8 BOM")

    def test_pending_only_current_day(self):
        self.db.upsert_item(RawItem("weibo", "昨天标题", "https://example.com/y"), "2026-10-27 08:00:00")
        self.db.upsert_item(RawItem("weibo", "今天标题", "https://example.com/t"), "2026-10-28 08:00:00")

        pending = self.db.pending_items("2026-10-28")
        self.assertEqual([row["title"] for row in pending], ["今天标题"])


class AIParsingTests(unittest.TestCase):
    def test_parse_fenced_json_and_clean_words(self):
        text = """```json
        {"items":[
          {"index":0,"hot_words":["雷军","#小米SU7#","网友"],"score":88.6,
           "reason":"理由","summary":"简介","category":"科技","is_junk":false}
        ]}
        ```"""
        parsed = parse_analysis_payload(text)
        self.assertIn(0, parsed)
        analysis = parsed[0]
        self.assertEqual(analysis.hot_words, ["雷军", "小米SU7"])
        self.assertEqual(analysis.score, 89)
        self.assertEqual(analysis.category, "科技")

    def test_parse_invalid_category_and_score(self):
        text = '{"items":[{"index":1,"hot_words":[],"score":"bad","category":"未知"}]}'
        parsed = parse_analysis_payload(text)
        self.assertEqual(parsed[1].score, 0)
        self.assertEqual(parsed[1].category, "其他")

    def test_parse_rejects_non_json(self):
        with self.assertRaises(ValueError):
            parse_analysis_payload("not json at all")


class SchedulerTests(unittest.TestCase):
    def test_next_run_same_day(self):
        now = datetime(2026, 10, 28, 7, 59, 0)
        self.assertEqual(
            next_run_at(now, ["00:00", "08:00", "16:00"]),
            datetime(2026, 10, 28, 8, 0, 0),
        )

    def test_next_run_next_day(self):
        now = datetime(2026, 10, 28, 21, 0, 0)
        self.assertEqual(
            next_run_at(now, ["00:00", "08:00", "16:00"]),
            datetime(2026, 10, 29, 0, 0, 0),
        )


if __name__ == "__main__":
    unittest.main()
