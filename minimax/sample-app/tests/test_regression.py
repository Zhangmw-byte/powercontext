"""既有行为回归测试（SPEC-001 / SPEC-002 / SPEC-005）。

这些用例在代码修改前后都必须全部通过，用于证明本次修改没有破坏原有行为。
"""

import pytest

from order_service import (
    VALID_STATUSES,
    advance_status,
    create_order,
    list_orders,
    summarize_orders,
)


def _sample_orders():
    return [
        create_order("o1", "alice", 10.0, "pending"),
        create_order("o2", "bob", 20.5, "paid"),
        create_order("o3", "carol", 30.0, "paid"),
        create_order("o4", "dave", 40.25, "shipped"),
    ]


def test_create_order_defaults_to_pending():
    order = create_order("o1", "alice", 9.9)
    assert order.status == "pending"
    assert order.amount == 9.9
    assert order.order_id == "o1"
    assert order.customer == "alice"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"order_id": "", "customer": "alice", "amount": 1.0},
        {"order_id": "o1", "customer": "  ", "amount": 1.0},
        {"order_id": "o1", "customer": "alice", "amount": 0},
        {"order_id": "o1", "customer": "alice", "amount": -3},
        {"order_id": "o1", "customer": "alice", "amount": 1.0, "status": "refunded"},
    ],
)
def test_create_order_rejects_invalid_input(kwargs):
    with pytest.raises(ValueError):
        create_order(**kwargs)


def test_list_orders_default_returns_all_in_creation_order():
    orders = _sample_orders()
    result = list_orders(orders)
    assert [o.order_id for o in result] == ["o1", "o2", "o3", "o4"]
    assert result is not orders


def test_advance_status_happy_path():
    order = create_order("o1", "alice", 1.0)
    paid = advance_status(order, "paid")
    assert paid.status == "paid"
    shipped = advance_status(paid, "shipped")
    assert shipped.status == "shipped"
    # 原对象不变
    assert order.status == "pending"
    assert paid.status == "paid"


@pytest.mark.parametrize(
    "current,new",
    [
        ("pending", "shipped"),
        ("shipped", "paid"),
        ("cancelled", "paid"),
        ("pending", "refunded"),
    ],
)
def test_advance_status_rejects_illegal_transition(current, new):
    order = create_order("o1", "alice", 1.0, current)
    with pytest.raises(ValueError):
        advance_status(order, new)


def test_advance_status_allows_cancel_from_pending_and_paid():
    pending = create_order("o1", "alice", 1.0)
    assert advance_status(pending, "cancelled").status == "cancelled"
    paid = advance_status(pending, "paid")
    assert advance_status(paid, "cancelled").status == "cancelled"


def test_summarize_orders():
    summary = summarize_orders(_sample_orders())
    assert summary["count"] == 4
    assert summary["total_amount"] == 100.75
    assert summary["by_status"] == {
        "pending": 1,
        "paid": 2,
        "shipped": 1,
        "cancelled": 0,
    }


def test_summarize_empty_orders():
    summary = summarize_orders([])
    assert summary["count"] == 0
    assert summary["total_amount"] == 0
    assert summary["by_status"] == {status: 0 for status in VALID_STATUSES}


def test_valid_statuses_are_the_expected_set():
    assert set(VALID_STATUSES) == {"pending", "paid", "shipped", "cancelled"}
