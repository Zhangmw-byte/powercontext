"""复习调度与清单生成的纯规则算法。

不依赖任何大模型:清单完全来自真实保存的掌握度、复习日期与每日时间预算,
采用 SM-2 风格的间隔重复调度。每条推荐附带规则化理由。
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from app.models import ReviewItem

_MIN_EASE = 1.3
_DEFAULT_EASE = 2.5
_DEFAULT_DAILY_MINUTES = 30


def _parse(date_str: str | None) -> date | None:
    if not date_str:
        return None
    try:
        return date.fromisoformat(date_str)
    except ValueError:
        return None


def apply_quality(record: dict[str, Any], quality: int, review_date: str) -> dict[str, Any]:
    """依据回忆质量更新单条学习记录的调度状态(返回新 payload,不改原对象)。"""
    ease = float(record.get("ease", _DEFAULT_EASE))
    reps = int(record.get("review_count", 0))
    interval = int(record.get("interval", 0))
    lapses = int(record.get("lapses", 0))

    if quality < 3:
        reps = 0
        interval = 1
        lapses += 1
    else:
        reps += 1
        if reps == 1:
            interval = 1
        elif reps == 2:
            interval = 6
        else:
            interval = max(1, round(interval * ease))

    ease = ease + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
    ease = round(max(_MIN_EASE, ease), 2)

    updated = dict(record)
    updated.update(
        {
            "mastery": int(quality),
            "last_review": review_date,
            "review_count": reps,
            "interval": interval,
            "ease": ease,
            "lapses": lapses,
        }
    )
    return updated


def _due_info(record: dict[str, Any], today: date) -> tuple[bool, int]:
    """返回 (是否到期, 逾期天数)。未复习过视为到期(逾期以 studied_on 估计)。"""
    last_review = _parse(record.get("last_review"))
    if last_review is None:
        return True, 0
    interval = int(record.get("interval", 0))
    due = last_review + timedelta(days=interval)
    overdue = (today - due).days
    return overdue >= 0, max(0, overdue)


def _priority_score(record: dict[str, Any], overdue_days: int) -> int:
    mastery = int(record.get("mastery", 0))
    lapses = int(record.get("lapses", 0))
    return (5 - mastery) * 2 + min(overdue_days, 30) + lapses


def _estimate_minutes(mastery: int) -> int:
    return max(2, 3 + (5 - mastery))


def generate_plan(
    records: list[dict[str, Any]],
    preference: dict[str, Any] | None,
    today: date,
) -> tuple[list[ReviewItem], int, str]:
    """由记录与偏好生成当日复习清单。

    返回 (清单条目, 每日预算分钟, 说明)。薄弱知识点优先,按预算裁剪。
    """
    daily_minutes = int((preference or {}).get("daily_minutes", _DEFAULT_DAILY_MINUTES))

    scored: list[tuple[int, int, dict[str, Any], int]] = []
    for rec in records:
        due, overdue = _due_info(rec, today)
        if not due:
            continue
        mastery = int(rec.get("mastery", 0))
        score = _priority_score(rec, overdue)
        scored.append((score, overdue, rec, mastery))

    scored.sort(key=lambda t: (t[0], t[1]), reverse=True)

    items: list[ReviewItem] = []
    used = 0
    for score, overdue, rec, mastery in scored:
        est = _estimate_minutes(mastery)
        if used + est > daily_minutes:
            continue
        used += est
        lapses = int(rec.get("lapses", 0))
        reasons: list[str] = []
        if mastery <= 2:
            reasons.append(f"薄弱(掌握度{mastery}/5)")
        elif mastery < 5:
            reasons.append(f"掌握度{mastery}/5,尚可")
        else:
            reasons.append("掌握度高,临间隔复习")
        if rec.get("last_review"):
            reasons.append(f"逾期{overdue}天" if overdue > 0 else "刚到复习间隔")
        else:
            reasons.append("尚未复习")
        if lapses:
            reasons.append(f"遗忘{lapses}次")
        items.append(
            ReviewItem(
                entry_id=rec["_entry_id"],
                topic=rec["topic"],
                course=rec["course"],
                mastery=mastery,
                reason=";".join(reasons),
                est_minutes=est,
                overdue_days=overdue,
            )
        )

    if not items:
        note = "当前没有到期需要复习的知识点,或每日时间预算过小无法安排任何条目。"
    else:
        note = (
            f"共{len(scored)}条到期记录,按薄弱与逾期优先、在{daily_minutes}分钟预算内选出{len(items)}条。"
            "(本清单由规则算法生成,未调用任何大模型。)"
        )
    return items, daily_minutes, note
