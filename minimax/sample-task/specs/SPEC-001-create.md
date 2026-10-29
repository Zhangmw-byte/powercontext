# SPEC-001 订单创建（既有行为，必须保持）

- 规格 ID：SPEC-001
- 类型：既有行为（回归约束）
- 关联代码：`sample-app/order_service/orders.py` → `create_order` / `VALID_STATUSES`
- 关联测试：`sample-app/tests/test_regression.py` 中创建相关用例

## 需求

`create_order(order_id, customer, amount, status="pending")`：

1. `order_id`、`customer` 必须是非空字符串；
2. `amount` 必须是大于 0 的有限数值；
3. `status` 必须是 `pending` / `paid` / `shipped` / `cancelled` 之一；
4. 缺省状态为 `pending`；
5. 校验失败抛出 `ValueError`。

## 验收

- 合法输入返回订单对象，字段与输入一致；
- 非法输入（空 id、空 customer、非正金额、未知状态）均抛出 `ValueError`。

## 兼容性

属于 SPEC-005 回归约束的一部分，本任务不得修改其行为。
