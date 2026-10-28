"""python_server 入口。

用法：
    python main.py                     # 常驻服务（默认）
    python main.py once [--no-ai]      # 立即跑一轮
    python main.py export --date DATE  # 重新导出指定日期
    python main.py sources --limit 3   # 测试数据源
    python main.py ping                # 测试 DeepSeek 连通性
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from app import __version__  # noqa: E402
from app.ai import AIConfigError, AIError, DeepSeekClient  # noqa: E402
from app.config import Config, load_config  # noqa: E402
from app.db import Database  # noqa: E402
from app.exporter import export_day  # noqa: E402
from app.lock import ProcessLock  # noqa: E402
from app.logging_setup import setup_logging  # noqa: E402
from app.pipeline import run_once  # noqa: E402
from app.scheduler import Daemon  # noqa: E402
from app.sources import SOURCE_LABELS, build_source  # noqa: E402
from app.utils import today_str  # noqa: E402

logger = logging.getLogger("main")


def setup_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                pass


def require_api_key(config: Config) -> bool:
    if config.ai.api_key:
        return True
    print(
        "未配置 DEEPSEEK_API_KEY。\n"
        f"请复制 {config.base_dir / '.env.example'} 为 .env，并填写你的 Key。\n"
        "申请地址：https://platform.deepseek.com/",
        file=sys.stderr,
    )
    return False


def cmd_daemon(config: Config) -> int:
    if not require_api_key(config):
        return 2

    lock = ProcessLock(config.data_dir / ".lock")
    if not lock.acquire():
        print("已有另一个实例在运行（data/.lock 被占用），本次退出。", file=sys.stderr)
        return 1

    db = Database(config.db_path)
    pid_path = config.data_dir / "service.pid"
    try:
        db.connect()
        pid_path.write_text(str(os.getpid()), encoding="utf-8")
        logger.info(
            "HotPulse python_server v%s | 数据库=%s | 导出目录=%s",
            __version__,
            config.db_path,
            config.export_dir,
        )
        Daemon(config, db).run_forever()
    finally:
        pid_path.unlink(missing_ok=True)
        db.close()
        lock.release()
    return 0


def cmd_once(config: Config, *, no_ai: bool) -> int:
    if not no_ai and not require_api_key(config):
        return 2

    lock = ProcessLock(config.data_dir / ".lock")
    if not lock.acquire():
        print("已有另一个实例在运行（data/.lock 被占用），本次退出。", file=sys.stderr)
        return 1

    db = Database(config.db_path)
    try:
        db.connect()
        summary = run_once(config, db, no_ai=no_ai)
    except Exception:  # noqa: BLE001
        logger.exception("执行一轮任务失败")
        return 1
    finally:
        db.close()
        lock.release()

    print(
        f"status={summary.status} 抓取={summary.fetched} 新增={summary.new_items} "
        f"分析={summary.analyzed}"
    )
    if summary.export_path:
        print(f"CSV: {summary.export_path}")
    if summary.message:
        print(f"message: {summary.message}")
    return 0 if summary.status in {"success", "partial"} else 1


def cmd_export(config: Config, day: str | None) -> int:
    target = day or today_str()
    try:
        datetime.strptime(target, "%Y-%m-%d")
    except ValueError:
        print(f"日期格式应为 YYYY-MM-DD，当前为 {target!r}", file=sys.stderr)
        return 2

    db = Database(config.db_path)
    try:
        db.connect()
        path = export_day(db, config, target)
        count = db.count_for_day(target)
    finally:
        db.close()

    print(f"已导出 {path}（{count} 条）")
    return 0


def cmd_sources(config: Config, limit: int) -> int:
    successes = 0
    for name in config.limits:
        label = SOURCE_LABELS.get(name, name)
        started = time.perf_counter()
        try:
            source = build_source(name, config)
            items = source.fetch(limit)
        except Exception as exc:  # noqa: BLE001
            elapsed = time.perf_counter() - started
            print(f"[FAIL] {label:<8} {elapsed:5.2f}s  {exc}")
            continue

        elapsed = time.perf_counter() - started
        print(f"[ OK ] {label:<8} {len(items):>3} 条  {elapsed:5.2f}s")
        for item in items[:3]:
            print(f"       - {item.title[:60]}")
        successes += 1

    return 0 if successes else 1


def cmd_ping(config: Config) -> int:
    if not require_api_key(config):
        return 2
    client = DeepSeekClient(config.ai)
    try:
        client.health_check()
    except AIConfigError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 1
    except AIError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 1
    print(f"[ OK ] DeepSeek 可用，model={config.ai.model}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="main.py",
        description="国内热榜抓取 + DeepSeek 分析 + 每日 CSV",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("daemon", help="常驻服务（默认）")

    once = subparsers.add_parser("once", help="立即执行一轮")
    once.add_argument("--no-ai", action="store_true", help="跳过 AI，只抓取并导出空分析列")

    export = subparsers.add_parser("export", help="重新导出某天的 CSV")
    export.add_argument("--date", default=None, help="YYYY-MM-DD，默认今天")

    sources = subparsers.add_parser("sources", help="测试各数据源可用性")
    sources.add_argument("--limit", type=int, default=5, help="每个源抓几条，默认 5")

    subparsers.add_parser("ping", help="测试 DeepSeek 连通性")
    return parser


def main(argv: list[str] | None = None) -> int:
    setup_console()
    args = build_parser().parse_args(argv)

    try:
        config = load_config()
    except Exception as exc:  # noqa: BLE001
        print(f"配置加载失败：{exc}", file=sys.stderr)
        return 2

    config.ensure_dirs()
    setup_logging(config.log_dir)

    command = args.command or "daemon"
    if command == "daemon":
        return cmd_daemon(config)
    if command == "once":
        return cmd_once(config, no_ai=args.no_ai)
    if command == "export":
        return cmd_export(config, args.date)
    if command == "sources":
        return cmd_sources(config, max(1, args.limit))
    if command == "ping":
        return cmd_ping(config)

    print(f"未知命令：{command}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
