"""配置加载：config.yaml 负责行为，.env 负责密钥。"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


@dataclass
class AIConfig:
    api_key: str = ""
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-chat"
    batch_size: int = 20
    timeout: int = 60
    retries: int = 3
    retry_delays: tuple[int, ...] = (5, 15, 30)
    max_tokens: int = 2600
    temperature: float = 0.2


@dataclass
class Config:
    base_dir: Path
    run_times: list[str]
    export_time: str
    limits: dict[str, int]
    ai: AIConfig
    data_dir: Path
    db_path: Path
    export_dir: Path
    log_dir: Path
    network_timeout: int = 15
    user_agent: str = DEFAULT_USER_AGENT

    def ensure_dirs(self) -> None:
        for path in (self.data_dir, self.export_dir, self.log_dir):
            path.mkdir(parents=True, exist_ok=True)


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _valid_time(value: str) -> bool:
    return bool(re.fullmatch(r"(?:[01]?\d|2[0-3]):[0-5]\d", value))


def _parse_run_times(raw: Any) -> list[str]:
    if isinstance(raw, str):
        raw = [item.strip() for item in raw.split(",") if item.strip()]
    if not isinstance(raw, (list, tuple)) or not raw:
        raw = ["00:00", "08:00", "16:00"]
    times: list[str] = []
    for item in raw:
        text = str(item).strip()
        if not _valid_time(text):
            raise ValueError(f"run_times 中的时间格式应为 HH:MM，当前为 {text!r}")
        hour, minute = (int(part) for part in text.split(":"))
        normalized = f"{hour:02d}:{minute:02d}"
        if normalized not in times:
            times.append(normalized)
    return sorted(times)


def _parse_sources(raw: Any) -> dict[str, int]:
    """支持两种写法：
    sources:
      weibo: 50
    或
    sources: [weibo, bilibili]
    """
    if isinstance(raw, dict):
        limits = {str(name): _as_int(limit, 50) for name, limit in raw.items()}
    elif isinstance(raw, (list, tuple)):
        limits = {str(name): 50 for name in raw}
    else:
        limits = {}
    return {name: max(1, limit) for name, limit in limits.items() if name}


def load_config(base_dir: Path | None = None) -> Config:
    base_dir = Path(base_dir or BASE_DIR)
    # utf-8-sig：兼容 Windows 记事本/部分编辑器保存 .env 时带 BOM 的情况
    load_dotenv(base_dir / ".env", encoding="utf-8-sig")

    raw: dict[str, Any] = {}
    config_file = base_dir / "config.yaml"
    if config_file.exists():
        with config_file.open("r", encoding="utf-8") as handle:
            raw = yaml.safe_load(handle) or {}
    if not isinstance(raw, dict):
        raise ValueError("config.yaml 顶层必须是键值对象")

    ai_raw = raw.get("ai") or {}
    network_raw = raw.get("network") or {}

    retry_delays = ai_raw.get("retry_delays") or [5, 15, 30]
    if not isinstance(retry_delays, (list, tuple)) or not retry_delays:
        retry_delays = [5, 15, 30]

    ai = AIConfig(
        api_key=os.getenv("DEEPSEEK_API_KEY", "").strip(),
        base_url=(
            os.getenv("DEEPSEEK_BASE_URL")
            or ai_raw.get("base_url")
            or "https://api.deepseek.com"
        ).strip(),
        model=(os.getenv("DEEPSEEK_MODEL") or ai_raw.get("model") or "deepseek-chat").strip(),
        batch_size=max(1, _as_int(ai_raw.get("batch_size"), 20)),
        timeout=max(10, _as_int(ai_raw.get("timeout"), 60)),
        retries=max(0, _as_int(ai_raw.get("retries"), 3)),
        retry_delays=tuple(max(0, _as_int(item, 5)) for item in retry_delays),
        max_tokens=max(200, _as_int(ai_raw.get("max_tokens"), 2600)),
        temperature=float(ai_raw.get("temperature", 0.2)),
    )

    run_times_raw = os.getenv("HOTSPOT_RUN_TIMES") or raw.get("run_times")
    run_times = _parse_run_times(run_times_raw)

    export_time = str(raw.get("export_time") or "23:50").strip()
    if not _valid_time(export_time):
        raise ValueError(f"export_time 格式应为 HH:MM，当前为 {export_time!r}")
    hour, minute = (int(part) for part in export_time.split(":"))
    export_time = f"{hour:02d}:{minute:02d}"

    limits = _parse_sources(raw.get("sources"))
    if not limits:
        limits = {"weibo": 50, "bilibili": 50, "zhihu": 50}

    data_dir = base_dir / "data"
    return Config(
        base_dir=base_dir,
        run_times=run_times,
        export_time=export_time,
        limits=limits,
        ai=ai,
        data_dir=data_dir,
        db_path=data_dir / "hotspot.db",
        export_dir=data_dir / "exports",
        log_dir=base_dir / "logs",
        network_timeout=max(5, _as_int(network_raw.get("timeout"), 15)),
        user_agent=str(network_raw.get("user_agent") or DEFAULT_USER_AGENT),
    )
