"""数据源基类：统一请求、超时、重试与错误类型。"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Any

import requests

from ..config import Config
from ..models import RawItem


class SourceError(Exception):
    """单个数据源不可用（网络、反爬、返回格式变化等）。"""


class BaseSource(ABC):
    name: str = ""
    label: str = ""

    def __init__(self, config: Config):
        self.config = config
        self.timeout = config.network_timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": config.user_agent,
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            }
        )

    def get_json(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        retries: int = 2,
    ) -> Any:
        last_error: Exception | None = None
        for attempt in range(retries + 1):
            try:
                response = self.session.get(
                    url,
                    params=params,
                    headers=headers,
                    timeout=self.timeout,
                )
                if response.status_code in (403, 429):
                    raise SourceError(f"HTTP {response.status_code}（被限流或需要登录）")
                if 400 <= response.status_code < 500:
                    raise SourceError(f"HTTP {response.status_code}")
                response.raise_for_status()
                return response.json()
            except SourceError:
                raise
            except (requests.RequestException, ValueError) as exc:
                last_error = exc
                if attempt < retries:
                    time.sleep(2 * (attempt + 1))
        raise SourceError(f"请求失败：{last_error}")

    @abstractmethod
    def fetch(self, limit: int) -> list[RawItem]:
        """抓取热榜，返回最多 limit 条。"""
        raise NotImplementedError
