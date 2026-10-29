"""订单服务示例业务代码（SDD 上下文管理系统的“被修改对象”）。

对应规格见 ``sample-task/specs/``。``list_orders`` 已实现 SPEC-003（按状态筛选）
与 SPEC-004（分页），其余函数提供题目要求的“原有行为”，保持不变（SPEC-005）。
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


# SPEC-004：分页参数取值范围（私有常量）
_MIN_PAGE_SIZE = 1
_MAX_PAGE_SIZE = 100


def _is_int(value: object) -> bool:
    """判断是否为整数（bool 不视为整数）。"""
    return isinstance(value, int) and not isinstance(value, bool)


def _validate_pagination(
    page: int | None, page_size: int | None
) -> tuple[int, int] | None:
    """校验分页参数（SPEC-004）。

    - ``page`` 必须是大于等于 1 的整数；
    - ``page_size`` 必须是 1～100 之间的整数（含边界）；
    - 两个参数必须成对出现（要么都传，要么都不传）；
    - 非法参数抛出 ``ValueError``。

    返回 ``(page, page_size)``；未分页时返回 ``None``。
    """
    if page is not None:
        if not _is_int(page):
            raise ValueError("page must be an integer")
        if page < 1:
            raise ValueError("page must be an integer greater than or equal to 1")
    if page_size is not None:
        if not _is_int(page_size):
            raise ValueError("page_size must be an integer")
        if not (_MIN_PAGE_SIZE <= page_size <= _MAX_PAGE_SIZE):
            raise ValueError(
                f"page_size must be an integer between {_MIN_PAGE_SIZE} "
                f"and {_MAX_PAGE_SIZE}"
            )
    if (page is None) != (page_size is None):
        raise ValueError("page and page_size must be provided together")
    if page is None or page_size is None:
        return None
    return page, page_size


def list_orders(
    orders: Iterable[Order],
    status: str | None = None,
    page: int | None = None,
    page_size: int | None = None,
) -> list[Order]:
    """返回订单列表（SPEC-002 默认查询 + SPEC-003 状态筛选 + SPEC-004 分页）。

    - ``status=None``（缺省）：返回全部订单，保持传入顺序（SPEC-002）；
    - ``status`` 为合法状态：只返回状态匹配的订单，保持原有相对顺序（SPEC-003）；
    - ``status`` 不在 ``VALID_STATUSES`` 中：抛出 ``ValueError``（SPEC-003）；
    - ``page`` / ``page_size`` 成对出现时，在筛选结果上分页；页码从 1 开始，
      ``page_size`` 取值 1～100；页码超出范围返回空列表（SPEC-004）。

    始终返回新的列表对象，不修改传入的订单集合。
    """
    if status is not None and status not in VALID_STATUSES:
        raise ValueError(f"unknown order status: {status!r}")
    pagination = _validate_pagination(page, page_size)

    result = list(orders)
    # SPEC-003：先筛选，保持原有相对顺序
    if status is not None:
        result = [order for order in result if order.status == status]
    # SPEC-004：筛选后再分页；页码越界自然得到空列表
    if pagination is not None:
        current_page, size = pagination
        start = (current_page - 1) * size
        result = result[start : start + size]
    return result


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
