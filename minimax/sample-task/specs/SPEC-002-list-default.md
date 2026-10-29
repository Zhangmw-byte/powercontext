# SPEC-002 订单列表：默认查询（既有行为，必须保持）

- 规格 ID：SPEC-002
- 类型：既有行为（回归约束）
- 关联代码：`sample-app/order_service/orders.py` → `list_orders`
- 关联测试：`sample-app/tests/test_regression.py::test_list_orders_default_returns_all_in_creation_order`

## 需求

`list_orders(orders)` 在不传筛选/分页参数时：

1. 返回全部订单，顺序与传入顺序一致（即创建顺序）；
2. 不修改传入的订单集合；
3. 返回新的列表对象，而不是原对象。

## 验收

- 传入 4 条订单，返回 4 条且 `order_id` 顺序不变；
- 返回列表与原输入不是同一个对象。

## 兼容性

本规格是 SPEC-003 / SPEC-004 的兼容基线：新增参数不得改变默认行为。
