# SPEC-004 订单列表：分页（本任务新增）

- 规格 ID：SPEC-004
- 类型：新增需求（本任务要实现）
- 关联代码：`sample-app/order_service/orders.py` → `list_orders`
- 关联测试：`sample-app/tests/test_target_feature.py` 中分页相关用例

## 需求

`list_orders(orders, page=..., page_size=...)`：

1. `page` 与 `page_size` 都为空时不分页，行为与 SPEC-002 一致；
2. 分页在筛选之后进行：先按 SPEC-003 过滤，再对结果切片；
3. `page` 为从 1 开始的整数；`page_size` 为 1～100 的整数（含边界）；
4. 以下情况抛出 `ValueError`：
   - `page` 传入但小于 1 或不是整数；
   - `page_size` 传入但小于 1、大于 100 或不是整数；
   - 只传了其中一个参数（必须成对出现，除非两个都不传）；
5. 页码超出结果范围时返回空列表（不报错）；
6. 结果为空时返回空列表，不报错。

## 验收

- `page=2, page_size=2` 返回筛选结果的第 3、4 条；
- `page=9, page_size=2` 返回空列表；
- `page=0`、`page_size=0`、`page_size=101` 均抛出 `ValueError`；
- 不传分页参数时结果与 SPEC-002 一致。

## 兼容性

- 分页不改变筛选与默认查询行为；
- 不修改传入的订单集合。
