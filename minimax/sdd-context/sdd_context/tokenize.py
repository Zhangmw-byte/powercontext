"""轻量分词：从任务描述中提取用于 seekdb 全文检索的词项。

不依赖任何分词模型：英文/标识符按词切分，中文按 2-gram / 3-gram 切分。
"""

from __future__ import annotations

import re
from collections import OrderedDict

_ASCII_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9_-]{1,}")
_CJK_RUN = re.compile(r"[\u4e00-\u9fff]+")

# 高频虚词/停用组合（只过滤纯由这些字组成的 2/3-gram）
_STOP_CHARS = set("的了和与在是有对中个就都而及或等这那为要从把被让给以于之其上下时后前可会能将并且但如果因为所以以及一个我们你他她它们")
_STOP_TERMS = {
    "订单列表",  # 保留？（出现频率高但区分度低，保留可帮助召回列表规格）
}
_STOP_TERMS.discard("订单列表")
_STOP_ASCII = {"the", "and", "for", "with", "this", "that", "from", "into", "than"}


def _cjk_grams(run: str) -> list[str]:
    grams: list[str] = []
    for n in (2, 3):
        for i in range(0, max(0, len(run) - n + 1)):
            gram = run[i : i + n]
            if all(ch in _STOP_CHARS for ch in gram):
                continue
            grams.append(gram)
    return grams


def extract_terms(text: str, limit: int = 60) -> list[str]:
    """提取检索词项（去重、保序、限制数量）。"""
    terms: "OrderedDict[str, None]" = OrderedDict()
    for token in _ASCII_TOKEN.findall(text or ""):
        low = token.lower()
        if low in _STOP_ASCII or low.isdigit():
            continue
        terms[low] = None
    for run in _CJK_RUN.findall(text or ""):
        for gram in _cjk_grams(run):
            if gram in _STOP_TERMS:
                continue
            terms[gram] = None
    return list(terms)[:limit]


def match_query(terms: list[str]) -> str:
    """拼成 MySQL FULLTEXT 允许的查询串（空格分隔，去掉会被当作操作符的字符）。"""
    cleaned = []
    for term in terms:
        term = re.sub(r"[+\-><()~*\"@]", " ", term).strip()
        if term:
            cleaned.append(term)
    return " ".join(cleaned)
