"""常驻调度：固定时间抓取，固定时间导出，不做补跑/补导。"""

from __future__ import annotations

import logging
import signal
import time
from datetime import datetime, time as dt_time, timedelta

from .ai import DeepSeekClient
from .config import Config
from .db import Database
from .exporter import export_day
from .pipeline import run_once

logger = logging.getLogger(__name__)


def _parse_hm(text: str) -> tuple[int, int]:
    hour, minute = (int(part) for part in text.split(":"))
    return hour, minute


def next_run_at(now: datetime, run_times: list[str]) -> datetime:
    """返回严格晚于 now 的下一个固定抓取时间。"""
    for day_offset in (0, 1, 2):
        base_date = now.date() + timedelta(days=day_offset)
        for text in run_times:
            hour, minute = _parse_hm(text)
            candidate = datetime.combine(base_date, dt_time(hour, minute))
            if candidate > now:
                return candidate
    # run_times 非空时不会到这里
    return now + timedelta(days=1)


class Daemon:
    def __init__(self, config: Config, db: Database, ai_client: DeepSeekClient | None = None):
        self.config = config
        self.db = db
        self.ai_client = ai_client or DeepSeekClient(config.ai)
        self.stop_flag = config.data_dir / "stop.flag"
        self._stop = False
        self._last_export_day: str | None = None

    # ------------------------------------------------------------------ 控制
    def stop(self) -> None:
        self._stop = True

    def _install_signals(self) -> None:
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, lambda *_: self.stop())
            except (ValueError, OSError):
                pass

    def _should_stop(self) -> bool:
        return self._stop or self.stop_flag.exists()

    # ------------------------------------------------------------------ 主循环
    def run_forever(self) -> None:
        if self.stop_flag.exists():
            self.stop_flag.unlink(missing_ok=True)

        self._install_signals()

        now = datetime.now()
        hour, minute = _parse_hm(self.config.export_time)
        export_target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if now >= export_target:
            # 启动时已过当天导出点：不补导，等下一个自然日
            self._last_export_day = now.strftime("%Y-%m-%d")

        next_run = next_run_at(now, self.config.run_times)
        logger.info(
            "后台服务启动：固定抓取 %s，每天 %s 导出 CSV，下次抓取 %s",
            " / ".join(self.config.run_times),
            self.config.export_time,
            next_run.strftime("%Y-%m-%d %H:%M"),
        )

        while not self._should_stop():
            now = datetime.now()

            if now >= next_run:
                try:
                    run_once(self.config, self.db, ai_client=self.ai_client)
                except Exception:  # noqa: BLE001 - 单轮失败不能拖垮常驻进程
                    logger.exception("本轮任务异常")
                next_run = next_run_at(datetime.now(), self.config.run_times)
                logger.info("下一次抓取：%s", next_run.strftime("%Y-%m-%d %H:%M"))

            self._maybe_daily_export(now)
            self._sleep_short()

        logger.info("后台服务已退出")

    def _maybe_daily_export(self, now: datetime) -> None:
        today = now.strftime("%Y-%m-%d")
        if self._last_export_day == today:
            return

        hour, minute = _parse_hm(self.config.export_time)
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if now < target:
            return

        try:
            export_day(self.db, self.config, today)
        except Exception:  # noqa: BLE001
            logger.exception("每日导出失败，等待下一轮重试")
            return
        self._last_export_day = today

    def _sleep_short(self) -> None:
        # 每秒检查停止标记，最多 15 秒，保证 23:50 导出和停止请求都够灵敏
        for _ in range(15):
            if self._should_stop():
                return
            time.sleep(1)
