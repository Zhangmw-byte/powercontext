"""应用侧数据模型、记忆条目编解码与字段校验。

SDK 记忆条目本体只有 ``kind`` 与 ``text`` 两个字段,没有数值列。
本模块把结构化业务字段编码为带版本标识 ``_v`` 的规范 JSON 文本写入 ``text``,
读取时再解析校验。规范 JSON 采用 ``sort_keys`` 且不含服务端易变时间戳,
使同一请求重复提交得到完全相同的 ``text``,从而复用 SDK 的内容级幂等去重。
"""

from __future__ import annotations

import json
from datetime import date as _date
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

# 记忆条目语义分类
KIND_LEARNER = "learner"        # 学习者注册表条目(存于注册 scope)
KIND_PREFERENCE = "preference"  # 学习偏好
KIND_RECORD = "record"          # 学习记录 / 知识点进度
SCHEMA_VERSION = 1

EntryKind = Literal["learner", "preference", "record"]


def encode_payload(payload: dict[str, Any]) -> str:
    """把业务字段编码为稳定、可去重的规范 JSON 文本。"""
    body = {"_v": SCHEMA_VERSION, **payload}
    return json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def decode_payload(text: str) -> dict[str, Any]:
    """解析条目文本;容忍非 JSON 的历史数据,退化为 ``{"raw": text}``。"""
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return {"_v": 0, "raw": text}
    if not isinstance(data, dict):
        return {"_v": 0, "raw": text}
    return data


def _validate_date(value: str | None) -> str | None:
    if value in (None, ""):
        return None
    _date.fromisoformat(value)  # 非法日期抛 ValueError
    return value


# --------------------------------------------------------------------------- #
# 请求体模型(带取值校验,拒绝非法数据进入记忆)
# --------------------------------------------------------------------------- #
class LearnerCreate(BaseModel):
    learner_id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=64)

    @field_validator("learner_id")
    @classmethod
    def _id_shape(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("learner_id 不能为空")
        if any(c in v for c in " /"):
            raise ValueError("learner_id 不能包含空格或斜杠")
        return v

    @field_validator("name")
    @classmethod
    def _name_shape(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name 不能为空")
        return v


class PreferenceIn(BaseModel):
    daily_minutes: int = Field(ge=1, le=600)
    goal: str = Field(default="", max_length=200)
    preferences: str = Field(default="", max_length=400)  # 偏好好自由文本

    @field_validator("goal", "preferences")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()

    def to_payload(self) -> dict[str, Any]:
        return {
            "kind": KIND_PREFERENCE,
            "daily_minutes": self.daily_minutes,
            "goal": self.goal,
            "preferences": self.preferences,
        }


class RecordIn(BaseModel):
    course: str = Field(min_length=1, max_length=120)
    topic: str = Field(min_length=1, max_length=120)
    note: str = Field(default="", max_length=1000)
    mastery: int = Field(ge=0, le=5)
    studied_on: str | None = None  # YYYY-MM-DD,可空

    @field_validator("course", "topic")
    @classmethod
    def _required_strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("课程与知识点不能为空")
        return v

    @field_validator("studied_on")
    @classmethod
    def _date_shape(cls, v: str | None) -> str | None:
        try:
            return _validate_date(v)
        except ValueError as exc:  # 转成 422 可读信息
            raise ValueError("studied_on 必须为 YYYY-MM-DD 日期") from exc

    def to_payload(self) -> dict[str, Any]:
        return {
            "kind": KIND_RECORD,
            "course": self.course,
            "topic": self.topic,
            "note": self.note.strip(),
            "mastery": self.mastery,
            "studied_on": self.studied_on,
        }


class ReviewResultIn(BaseModel):
    """复习结果回写:针对某知识点记录,更新掌握度与复习调度。"""

    topic: str = Field(min_length=1, max_length=120)
    quality: int = Field(ge=0, le=5)         # 回忆质量,映射新掌握度
    review_date: str                         # 必填以保证重复提交可去重
    mastery: int | None = None               # 可选显式新掌握度

    @field_validator("topic")
    @classmethod
    def _topic_strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("topic 不能为空")
        return v

    @field_validator("review_date")
    @classmethod
    def _review_date_shape(cls, v: str) -> str:
        try:
            return _validate_date(v) or v
        except ValueError as exc:
            raise ValueError("review_date 必须为 YYYY-MM-DD 日期") from exc


# --------------------------------------------------------------------------- #
# 响应模型
# --------------------------------------------------------------------------- #
class LearnerOut(BaseModel):
    learner_id: str
    name: str
    scope_id: str


class RecordOut(BaseModel):
    entry_id: str
    entry_version_id: str
    version: int
    course: str
    topic: str
    note: str
    mastery: int
    studied_on: str | None
    last_review: str | None
    review_count: int
    interval: int
    ease: float
    lapses: int


class PreferenceOut(BaseModel):
    entry_id: str | None
    daily_minutes: int
    goal: str
    preferences: str
    version: int


class ReviewItem(BaseModel):
    entry_id: str
    topic: str
    course: str
    mastery: int
    reason: str
    est_minutes: int
    overdue_days: int


class ReviewPlan(BaseModel):
    learner_id: str
    generated_on: str
    daily_minutes: int
    total_est_minutes: int
    items: list[ReviewItem]
    note: str


class MemoryEntryView(BaseModel):
    entry_id: str
    entry_version_id: str
    version: int
    kind: str
    text: str
    state: str
    created_in_revision: int
    payload: dict[str, Any]


class VerificationView(BaseModel):
    scope_id: str
    memory_artifact_id: str
    revision: int
    entry_count: int
    entries: list[MemoryEntryView]


class RevisionSnapshot(BaseModel):
    revision: int
    changes: list[dict[str, Any]]
    entries: list[MemoryEntryView]
