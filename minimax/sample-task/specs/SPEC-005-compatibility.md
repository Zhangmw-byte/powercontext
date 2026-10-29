# SPEC-005 订单服务其他既有行为（回归约束）

- 规格 ID：SPEC-005
- 类型：既有行为（回归约束，不得破坏）
- 关联代码：`sample-app/order_service/orders.py` → `create_order` / `advance_status` / `summarize_orders`
- 关联测试：`sample-app/tests/test_regression.py`

## 需求

1. `create_order(order_id, customer, amount, status="pending")`：
   - `order_id`、`customer` 非空字符串，否则 `ValueError`；
   - `amount` 为大于 0 的有限数值，否则 `ValueError`；
   - `status` 必须是 `VALID_STATUSES` 之一，否则 `ValueError`；
   - 默认状态为 `pending`。
2. `advance_status(order, new_status)`：
   - 状态流转按 `ALLOWED_TRANSITIONS`：pending→paid/cancelled，paid→shipped/cancelled，shipped/cancelled 为终态；
   - 非法状态或非法流转抛出 `ValueError`；
   - 返回新的 `Order`，不修改原对象。
3. `summarize_orders(orders)`：
   - 返回 `count`、`total_amount`（保留 2 位小数）、`by_status`（包含全部状态，无订单为 0）；
   - 空输入返回 count=0、total_amount=0、各状态计数为 0。

## 验收

- 修改前后，`sample-app/tests/test_regression.py` 全部通过；
- 不得通过修改预期结果或删除断言来让测试通过。
