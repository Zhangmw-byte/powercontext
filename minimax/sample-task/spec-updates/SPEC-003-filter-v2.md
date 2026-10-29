# SPEC-003 订单列表：按状态筛选（v2 更新版，用于“规格更新后重新导入”演示）

- 规格 ID：SPEC-003
- 类型：新增需求（本任务要实现）
- 关联代码：`sample-app/order_service/orders.py` → `list_orders`
- 关联测试：`sample-app/tests/test_target_feature.py` 中的筛选相关用例

## v2 更新（2026-10-29）

- 新增说明：状态筛选与分页可以组合使用，分页必须在筛选之后执行。
- 错误信息要求：参数非法时抛出的 `ValueError` 消息中应包含参数名（`status` / `page` / `page_size`）。
- 其余需求与 v1 一致。

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
