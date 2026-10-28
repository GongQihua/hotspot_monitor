"""数据源注册表。新增源只需在这里登记。"""

from __future__ import annotations

from ..config import Config
from .base import BaseSource, SourceError
from .bilibili import BilibiliSource
from .weibo import WeiboSource
from .zhihu import ZhihuSource

SOURCE_CLASSES: dict[str, type[BaseSource]] = {
    WeiboSource.name: WeiboSource,
    BilibiliSource.name: BilibiliSource,
    ZhihuSource.name: ZhihuSource,
}

SOURCE_LABELS: dict[str, str] = {
    WeiboSource.name: WeiboSource.label,
    BilibiliSource.name: BilibiliSource.label,
    ZhihuSource.name: ZhihuSource.label,
}


def build_source(name: str, config: Config) -> BaseSource:
    source_class = SOURCE_CLASSES.get(name)
    if source_class is None:
        available = ", ".join(sorted(SOURCE_CLASSES))
        raise SourceError(f"未知数据源 {name!r}，可用：{available}")
    return source_class(config)
