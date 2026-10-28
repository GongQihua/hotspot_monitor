"""微博热搜。"""

from __future__ import annotations

from urllib.parse import quote

from ..models import RawItem
from ..utils import clean_text
from .base import BaseSource


class WeiboSource(BaseSource):
    name = "weibo"
    label = "微博热搜"
    URL = "https://weibo.com/ajax/side/hotSearch"

    def fetch(self, limit: int) -> list[RawItem]:
        payload = self.get_json(
            self.URL,
            headers={
                "Referer": "https://weibo.com/",
                "Accept": "application/json, text/plain, */*",
            },
        )
        realtime = ((payload or {}).get("data") or {}).get("realtime") or []
        items: list[RawItem] = []

        for position, entry in enumerate(realtime, start=1):
            if not isinstance(entry, dict) or entry.get("is_ad"):
                continue

            word = clean_text(entry.get("word"))
            note = clean_text(entry.get("note"))
            title = (note or word).strip("#＃ ")
            if not title:
                continue

            topic = word or title
            heat = entry.get("num")
            try:
                heat = int(heat) if heat is not None else None
            except (TypeError, ValueError):
                heat = None

            items.append(
                RawItem(
                    source=self.name,
                    title=title,
                    url="https://s.weibo.com/weibo?q=" + quote(f"#{topic}#"),
                    source_id=str(entry.get("mid") or topic),
                    rank=position,
                    raw_heat=heat,
                    extra={
                        "category": entry.get("category"),
                        "word": topic,
                    },
                )
            )
            if len(items) >= limit:
                break

        return items
