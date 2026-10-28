"""数据模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .utils import title_hash


@dataclass
class RawItem:
    """数据源返回的一条原始榜单内容。"""

    source: str
    title: str
    url: str
    source_id: str | None = None
    rank: int | None = None
    raw_heat: int | None = None
    published_at: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def title_hash(self) -> str:
        return title_hash(self.title)


@dataclass
class Analysis:
    """AI 对一条标题的分析结果。"""

    hot_words: list[str]
    score: int
    reason: str
    summary: str
    category: str = "其他"
    is_junk: bool = False
