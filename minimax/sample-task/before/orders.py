"""订单服务示例业务代码（SDD 上下文管理系统的“被修改对象”）。

对应规格见 ``sample-task/specs/``。本文件是**修改前**的初始版本：
``list_orders`` 尚未实现 SPEC-003（按状态筛选）与 SPEC-004（分页），
其余函数提供题目要求的“原有行为”，修改后必须保持不变（SPEC-005）。
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Iterable

# SPEC-001：订单状态取值
VALID_STATUSES: tuple[str, ...] = ("pending", "paid", "shipped", "cancelled")

# SPEC-005：状态流转规则（既有行为）
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"paid", "cancelled"},
    "paid": {"shipped", "cancelled"},
    "shipped": set(),
    "cancelled": set(),
}


@dataclass(frozen=True)
class Order:
    """一条订单记录。"""

    order_id: str
    customer: str
    amount: float
    status: str = "pending"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def as_dict(self) -> dict:
        """返回用于展示/序列化的字典。"""
        return {
            "order_id": self.order_id,
            "customer": self.customer,
            "amount": self.amount,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
        }


def create_order(
    order_id: str,
    customer: str,
    amount: float,
    status: str = "pending",
) -> Order:
    """创建订单（SPEC-001）。

    - order_id / customer 必须是非空字符串
    - amount 必须是大于 0 的有限数值
    - status 必须是 VALID_STATUSES 之一
    """
    if not isinstance(order_id, str) or not order_id.strip():
        raise ValueError("order_id must be a non-empty string")
    if not isinstance(customer, str) or not customer.strip():
        raise ValueError("customer must be a non-empty string")
    if not isinstance(amount, (int, float)) or isinstance(amount, bool):
        raise ValueError("amount must be a number")
    if amount <= 0 or amount != amount or amount in (float("inf"), float("-inf")):
        raise ValueError("amount must be a positive finite number")
    if status not in VALID_STATUSES:
        raise ValueError(f"unknown order status: {status!r}")
    return Order(
        order_id=order_id.strip(),
        customer=customer.strip(),
        amount=float(amount),
        status=status,
    )


def list_orders(
    orders: Iterable[Order],
    status: str | None = None,
    page: int | None = None,
    page_size: int | None = None,
) -> list[Order]:
    """按创建顺序返回订单列表（SPEC-002 默认查询）。

    当前实现只做默认查询：返回全部订单，保持传入顺序。

    TODO(SPEC-003)：实现 status 状态筛选。
    TODO(SPEC-004)：实现 page/page_size 分页；参数校验见规格。
    """
    # 修改前：status/page/page_size 是预留参数，尚未实现，传入后被忽略。
    return list(orders)


def advance_status(order: Order, new_status: str) -> Order:
    """推进订单状态（SPEC-005 既有行为）。

    允许的流转见 ALLOWED_TRANSITIONS；非法状态或非法流转抛出 ValueError。
    返回新的 Order，不修改原对象。
    """
    if new_status not in VALID_STATUSES:
        raise ValueError(f"unknown order status: {new_status!r}")
    allowed = ALLOWED_TRANSITIONS.get(order.status, set())
    if new_status not in allowed:
        raise ValueError(f"illegal transition: {order.status!r} -> {new_status!r}")
    return replace(order, status=new_status)


def summarize_orders(orders: Iterable[Order]) -> dict:
    """汇总订单（SPEC-005 既有行为）。

    返回 {"count": 总数, "total_amount": 总金额（保留 2 位）, "by_status": 各状态计数}。
    by_status 固定包含 VALID_STATUSES 中的全部状态（没有订单的状态计数为 0）。
    """
    order_list = list(orders)
    by_status = {status: 0 for status in VALID_STATUSES}
    total = 0.0
    for order in order_list:
        by_status[order.status] += 1
        total += order.amount
    return {
        "count": len(order_list),
        "total_amount": round(total, 2),
        "by_status": by_status,
    }
