# 验证样例任务：订单列表增加状态筛选与分页

> 本文件是 SDD 上下文管理系统验证样例的**任务描述**。评审可按本文件复现完整流程：
> 导入资料 → 生成上下文 → 把上下文交给使用 MiniMax 的开发助手 → 修改代码 → 跑测试。

## 1. 要改什么

在 `sample-app/order_service/orders.py` 的 `list_orders` 中实现两个新需求：

| 规格 | 内容 | 状态 |
|---|---|---|
| SPEC-003 | `status` 参数：按订单状态筛选，缺省（None）返回全部；非法状态抛 `ValueError` | 待实现 |
| SPEC-004 | `page` / `page_size` 参数：在筛选结果上分页；参数校验见规格 | 待实现 |

允许新增私有辅助函数或常量；**不要修改测试文件**，不要改动与本次需求无关的代码。

## 2. 哪些原有行为必须保持（SPEC-005）

- `list_orders(orders)` 不传新增参数时：返回全部订单、保持传入顺序、不修改输入（SPEC-002）
- `create_order` 的输入校验与默认状态（SPEC-001）
- `advance_status` 的状态流转规则（SPEC-005）
- `summarize_orders` 的输出结构与数值（SPEC-005）

## 3. 验收标准

1. **修改前**：`pytest tests/test_target_feature.py` 失败（功能未实现），`pytest tests/test_regression.py` 全部通过；
2. **修改后**：`pytest tests/test_target_feature.py` 与 `pytest tests/test_regression.py` 全部通过；
3. 测试集在修改前后保持一致，不得删除断言、跳过测试或修改预期结果；
4. 修改后的代码差异（diff）与本任务规格逐条对应。

## 4. 关联资料（上下文模块应选出的来源）

- 规格：`sample-task/specs/SPEC-002-list-default.md`、`SPEC-003-filter.md`、`SPEC-004-pagination.md`、`SPEC-005-compatibility.md`
- 代码：`sample-app/order_service/orders.py`（`Order` / `create_order` / `list_orders` / `advance_status` / `summarize_orders`）
- 测试：`sample-app/tests/test_target_feature.py`、`sample-app/tests/test_regression.py`

## 5. 预期结果

- 目标测试 10 条：修改前 8 条失败、2 条通过（默认行为用例）；修改后 10 条全部通过；
- 回归测试 16 条全部通过（修改前后都通过）；
- `list_orders` 实现符合 SPEC-003 / SPEC-004，默认行为与 SPEC-002 一致。
