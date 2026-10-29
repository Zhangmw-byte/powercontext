"""目标功能测试（SPEC-003 / SPEC-004）。

本次代码修改的目标：为 ``list_orders`` 实现按状态筛选与分页。
这些用例在修改前应当失败（功能未实现），修改后必须全部通过。
"""

import pytest

from order_service import create_order, list_orders


def _sample_orders():
    """按创建顺序 o1..o5；其中 paid 状态的是 o2、o3。"""
    return [
        create_order("o1", "alice", 10.0, "pending"),
        create_order("o2", "bob", 20.0, "paid"),
        create_order("o3", "carol", 30.0, "paid"),
        create_order("o4", "dave", 40.0, "shipped"),
        create_order("o5", "erin", 50.0, "paid"),
    ]


def test_filter_returns_only_matching_status():
    result = list_orders(_sample_orders(), status="paid")
    assert [o.order_id for o in result] == ["o2", "o3", "o5"]


def test_filter_preserves_creation_order():
    result = list_orders(_sample_orders(), status="paid")
    order_ids = [o.order_id for o in result]
    assert order_ids == sorted(order_ids, key=lambda x: int(x[1:]))


def test_filter_rejects_unknown_status():
    with pytest.raises(ValueError):
        list_orders(_sample_orders(), status="refunded")


def test_pagination_applies_after_filter():
    page2 = list_orders(_sample_orders(), status="paid", page=2, page_size=2)
    assert [o.order_id for o in page2] == ["o5"]


def test_pagination_keeps_default_order_without_filter():
    result = list_orders(_sample_orders(), page=2, page_size=2)
    assert [o.order_id for o in result] == ["o3", "o4"]


def test_pagination_page_beyond_range_returns_empty_list():
    assert list_orders(_sample_orders(), page=9, page_size=2) == []


def test_pagination_validates_page():
    with pytest.raises(ValueError):
        list_orders(_sample_orders(), page=0)


def test_pagination_validates_page_size():
    with pytest.raises(ValueError):
        list_orders(_sample_orders(), page_size=0)
    with pytest.raises(ValueError):
        list_orders(_sample_orders(), page_size=101)


def test_status_and_pagination_combined_with_empty_result():
    # 类型筛选后没有数据时返回空列表，而不是报错
    assert list_orders(_sample_orders(), status="cancelled", page=1, page_size=10) == []


def test_default_call_behavior_unchanged():
    # SPEC-002 / SPEC-005：不传新增参数时行为与修改前一致
    assert [o.order_id for o in list_orders(_sample_orders())] == [
        "o1",
        "o2",
        "o3",
        "o4",
        "o5",
    ]
