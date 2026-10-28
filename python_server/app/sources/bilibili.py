"""B站热门视频。"""

from __future__ import annotations

import uuid
from datetime import datetime

from ..models import RawItem
from ..utils import clean_text
from .base import BaseSource, SourceError


class BilibiliSource(BaseSource):
    name = "bilibili"
    label = "B站热门"
    URL = "https://api.bilibili.com/x/web-interface/popular"

    def fetch(self, limit: int) -> list[RawItem]:
        # buvid3 可以显著降低 412 概率
        buvid3 = f"{uuid.uuid4()}infoc"
        payload = self.get_json(
            self.URL,
            params={"ps": min(max(limit, 1), 50), "pn": 1},
            headers={
                "Referer": "https://www.bilibili.com/",
                "Accept": "application/json, text/plain, */*",
                "Cookie": f"buvid3={buvid3}",
            },
        )

        if not isinstance(payload, dict) or int(payload.get("code", -1)) != 0:
            raise SourceError(f"B站接口返回异常：{payload!r:.200}")

        videos = ((payload.get("data") or {}).get("list") or [])
        items: list[RawItem] = []

        for position, video in enumerate(videos, start=1):
            if not isinstance(video, dict):
                continue
            title = clean_text(video.get("title"))
            bvid = clean_text(video.get("bvid"))
            if not title or not bvid:
                continue

            stat = video.get("stat") or {}
            owner = video.get("owner") or {}

            raw_heat = stat.get("view")
            try:
                raw_heat = int(raw_heat) if raw_heat is not None else None
            except (TypeError, ValueError):
                raw_heat = None

            published_at = None
            pubdate = video.get("pubdate")
            if pubdate:
                try:
                    published_at = datetime.fromtimestamp(int(pubdate)).strftime(
                        "%Y-%m-%d %H:%M:%S"
                    )
                except (TypeError, ValueError, OSError):
                    published_at = None

            items.append(
                RawItem(
                    source=self.name,
                    title=title,
                    url=f"https://www.bilibili.com/video/{bvid}",
                    source_id=bvid,
                    rank=position,
                    raw_heat=raw_heat,
                    published_at=published_at,
                    extra={
                        "author": clean_text(owner.get("name")),
                        "category": clean_text(video.get("tname")),
                        "like": stat.get("like"),
                        "danmaku": stat.get("danmaku"),
                        "reply": stat.get("reply"),
                        "desc": clean_text(video.get("desc"))[:200],
                    },
                )
            )
            if len(items) >= limit:
                break

        return items
