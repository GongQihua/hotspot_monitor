"""单轮任务：抓取 → 去重入库 → AI 分析 → 导出当天 CSV。"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from .ai import AIConfigError, AIError, AIServiceError, DeepSeekClient
from .config import Config
from .db import Database
from .exporter import export_day
from .models import RawItem
from .sources import build_source
from .utils import chunked, clean_text, iso, now_local

logger = logging.getLogger(__name__)


@dataclass
class RunSummary:
    run_id: int
    status: str
    fetched: int = 0
    new_items: int = 0
    analyzed: int = 0
    export_path: Path | None = None
    message: str = ""
    errors: list[str] = field(default_factory=list)


def _finish(
    db: Database,
    run_id: int,
    *,
    status: str,
    fetched: int,
    new_items: int,
    analyzed: int,
    errors: Sequence[str],
    export_path: Path | None = None,
) -> RunSummary:
    message = "; ".join(errors)
    finished_at = iso(now_local())
    db.finish_run(
        run_id,
        status=status,
        fetched=fetched,
        new_items=new_items,
        analyzed=analyzed,
        message=message,
        finished_at=finished_at,
    )
    return RunSummary(
        run_id=run_id,
        status=status,
        fetched=fetched,
        new_items=new_items,
        analyzed=analyzed,
        export_path=export_path,
        message=message,
        errors=list(errors),
    )


def run_once(
    config: Config,
    db: Database,
    *,
    no_ai: bool = False,
    ai_client: DeepSeekClient | None = None,
    source_names: Sequence[str] | None = None,
) -> RunSummary:
    started_at = iso(now_local())
    run_time = started_at
    day = run_time[:10]
    names = list(source_names or config.limits.keys())
    run_id = db.start_run(started_at, names)

    errors: list[str] = []
    fetched = 0
    new_items = 0
    analyzed = 0

    # 1. AI 健康检查：不通过则放弃本轮（不抓取）
    if not no_ai:
        if ai_client is None:
            ai_client = DeepSeekClient(config.ai)
        try:
            ai_client.health_check()
        except AIConfigError as exc:
            logger.error("AI 配置错误，本轮终止：%s", exc)
            return _finish(
                db,
                run_id,
                status="config_error",
                fetched=0,
                new_items=0,
                analyzed=0,
                errors=[str(exc)],
            )
        except AIServiceError as exc:
            logger.error("AI 服务不可用，本轮放弃：%s", exc)
            return _finish(
                db,
                run_id,
                status="ai_unavailable",
                fetched=0,
                new_items=0,
                analyzed=0,
                errors=[str(exc)],
            )

    # 2. 逐个源抓取并入库
    for name in names:
        limit = config.limits.get(name, 50)
        try:
            source = build_source(name, config)
            raw_items = source.fetch(limit)
        except Exception as exc:  # noqa: BLE001 - 单源失败不影响其他源
            logger.error("数据源 %s 抓取失败：%s", name, exc)
            errors.append(f"{name}: {exc}")
            continue

        logger.info("数据源 %s 抓取到 %s 条", name, len(raw_items))
        for position, raw in enumerate(raw_items, start=1):
            raw.title = clean_text(raw.title)
            raw.url = clean_text(raw.url)
            if not raw.title or not raw.url:
                continue
            if len(clean_text(raw.title)) < 2:
                continue
            if raw.rank is None:
                raw.rank = position

            try:
                _, is_new = db.upsert_item(raw, run_time)
            except Exception as exc:  # noqa: BLE001
                logger.exception("入库失败：%s", raw.title)
                errors.append(f"入库失败: {exc}")
                continue
            fetched += 1
            if is_new:
                new_items += 1

    # 3. 分析当天待处理条目（历史未分析且当天重新出现的，也会在这里补上）
    if not no_ai:
        assert ai_client is not None
        pending = db.pending_items(day, limit=500)
        logger.info("待分析 %s 条", len(pending))
        for batch in chunked(pending, config.ai.batch_size):
            batch_rows = list(batch)
            try:
                results = ai_client.analyze_batch(batch_rows)
            except AIConfigError as exc:
                logger.error("AI 配置错误，停止分析：%s", exc)
                db.mark_attempt([int(row["id"]) for row in batch_rows], str(exc))
                errors.append(str(exc))
                break
            except AIError as exc:
                logger.error("AI 分析失败，留待下轮：%s", exc)
                db.mark_attempt([int(row["id"]) for row in batch_rows], str(exc))
                errors.append(str(exc))
                break

            missing: list[int] = []
            for row in batch_rows:
                item_id = int(row["id"])
                analysis = results.get(item_id)
                if analysis is None:
                    missing.append(item_id)
                    continue
                db.save_analysis(item_id, analysis, ai_client.model, iso(now_local()))
                analyzed += 1

            if missing:
                db.mark_attempt(missing, "模型返回中缺少该条")
                errors.append(f"模型漏返回 {len(missing)} 条")
                logger.warning("模型漏返回 %s 条", len(missing))

    # 4. 导出当天 CSV（每轮刷新一次，最终以 23:50 那次为准）
    export_path: Path | None = None
    try:
        export_path = export_day(db, config, day)
    except Exception as exc:  # noqa: BLE001
        logger.exception("导出 CSV 失败")
        errors.append(f"导出失败: {exc}")

    status = "partial" if errors else "success"
    summary = _finish(
        db,
        run_id,
        status=status,
        fetched=fetched,
        new_items=new_items,
        analyzed=analyzed,
        errors=errors,
        export_path=export_path,
    )
    logger.info(
        "本轮结束：status=%s，抓取=%s，新增=%s，分析=%s，导出=%s",
        summary.status,
        summary.fetched,
        summary.new_items,
        summary.analyzed,
        summary.export_path,
    )
    return summary
