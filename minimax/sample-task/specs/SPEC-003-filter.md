# SPEC-003 订单列表：按状态筛选（本任务新增）

- 规格 ID：SPEC-003
- 类型：新增需求（本任务要实现）
- 关联代码：`sample-app/order_service/orders.py` → `list_orders`
- 关联测试：`sample-app/tests/test_target_feature.py` 中的筛选相关用例

## 需求

`list_orders(orders, status=...)`：

1. `status=None` 时行为与 SPEC-002 完全一致（返回全部、保持顺序）；
2. `status` 为合法状态（`VALID_STATUSES`：pending / paid / shipped / cancelled）时，
   只返回状态匹配的订单，且保持原有相对顺序；
3. `status` 不在 `VALID_STATUSES` 中时，抛出 `ValueError`；
4. 不修改传入的订单集合。

## 验收

- `status="paid"` 只返回状态为 paid 的订单，顺序与创建顺序一致；
- `status="refunded"`（非法值）抛出 `ValueError`；
- `status=None` 返回全部订单（与 SPEC-002 一致）。

## 兼容性

- 本规格不得改变 SPEC-002 的默认行为；
- 与 SPEC-004（分页）组合时，先筛选后分页。
