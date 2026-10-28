"""通用工具：标题归一化、时间、热度解析、分批。"""

from __future__ import annotations

import hashlib
import html
import re
import unicodedata
from datetime import datetime
from typing import Iterable, Iterator, Sequence, TypeVar

T = TypeVar("T")


def now_local() -> datetime:
    """使用服务器本地时间（本项目默认 Asia/Shanghai）。"""
    return datetime.now()


def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def today_str() -> str:
    return now_local().strftime("%Y-%m-%d")


def clean_text(value: object) -> str:
    if value is None:
        return ""
    text = html.unescape(str(value))
    text = text.replace("\u200b", "").replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def normalize_title(title: str) -> str:
    """用于去重的标题指纹：全半角统一、去空白和标点、忽略大小写。

    "＃雷军# 回应" 与 "#雷军#回应"、"iPhone 17 发布！" 与 "iPhone17发布"
    会得到相同结果。
    """
    text = unicodedata.normalize("NFKC", title or "")
    text = text.replace("#", "").replace("＃", "")
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"[^\w\u4e00-\u9fff]+", "", text)
    text = text.replace("_", "")
    return text.casefold()


def title_hash(title: str) -> str:
    return hashlib.sha1(normalize_title(title).encode("utf-8")).hexdigest()


def parse_heat(value: object) -> int | None:
    """把 "523 万热度"、"1.2亿"、"1234567" 统一成整数。"""
    text = clean_text(value)
    if not text:
        return None
    match = re.search(r"(\d+(?:\.\d+)?)\s*(亿|万)?", text)
    if not match:
        return None
    number = float(match.group(1))
    unit = match.group(2)
    if unit == "亿":
        number *= 100_000_000
    elif unit == "万":
        number *= 10_000
    return int(round(number))


def chunked(items: Sequence[T], size: int) -> Iterator[Sequence[T]]:
    size = max(1, size)
    for start in range(0, len(items), size):
        yield items[start : start + size]


def dedupe_keep_order(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result
