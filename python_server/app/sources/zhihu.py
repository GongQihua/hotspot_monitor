"""知乎热榜。"""

from __future__ import annotations

from ..models import RawItem
from ..utils import clean_text, parse_heat
from .base import BaseSource


class ZhihuSource(BaseSource):
    name = "zhihu"
    label = "知乎热榜"
    # www.zhihu.com 的接口现在要求登录（401），api.zhihu.com 仍可匿名访问
    URL = "https://api.zhihu.com/topstory/hot-lists/total"

    def fetch(self, limit: int) -> list[RawItem]:
        payload = self.get_json(
            self.URL,
            params={"limit": min(max(limit, 1), 50), "reverse_order": 0},
            headers={
                "Referer": "https://www.zhihu.com/hot",
                "Accept": "application/json, text/plain, */*",
            },
        )

        entries = (payload or {}).get("data") or []
        items: list[RawItem] = []

        for position, entry in enumerate(entries, start=1):
            if not isinstance(entry, dict):
                continue
            target = entry.get("target") or {}
            if not isinstance(target, dict):
                continue

            title = clean_text(target.get("title"))
            if not title:
                continue

            target_id = target.get("id")
            target_type = target.get("type") or "question"
            if target_id and target_type == "article":
                url = f"https://zhuanlan.zhihu.com/p/{target_id}"
            elif target_id:
                url = f"https://www.zhihu.com/question/{target_id}"
            else:
                url = clean_text(target.get("url"))
            if not url:
                continue

            items.append(
                RawItem(
                    source=self.name,
                    title=title,
                    url=url,
                    source_id=str(target_id) if target_id else None,
                    rank=position,
                    raw_heat=parse_heat(entry.get("detail_text")),
                    extra={
                        "detail_text": clean_text(entry.get("detail_text")),
                        "excerpt": clean_text(target.get("excerpt"))[:300],
                    },
                )
            )
            if len(items) >= limit:
                break

        return items
