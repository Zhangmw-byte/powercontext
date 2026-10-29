你是本次 SDD 任务的开发助手（使用 MiniMax M3.1 Flash）。工作目录是当前目录（minimax/ 交付目录）。

下面给你两样东西：
1) 任务描述
2) 上下文模块根据任务从 seekdb 检索出的工程上下文（规格 / 代码 / 测试 / 任务状态）

请严格按上下文中的规格完成任务：只修改 sample-app/order_service/orders.py 中 list_orders 的实现
（允许新增私有辅助函数），不要修改测试文件、不要删除断言或跳过测试，不要改动无关代码。
修改后运行下面两条命令，并把测试结果摘要（通过/失败数量）回复给我：
  cd sample-app && python -m pytest tests/test_target_feature.py -q
  cd sample-app && python -m pytest tests/test_regression.py -q

=== 任务描述 ===
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


=== SDD 上下文包 ===
# SDD 任务上下文包

- 生成时间：2026-10-29T10:41:09+08:00
- 数据库查询 ID：q-20261029024109114911
- 检索词：sdd、minimax、sample-app、order_service、orders、py、list_orders、spec-003、status、none、valueerror、spec-004、page、page_size、spec-005、spec-002、create_order、spec-001、advance_status、summarize_orders、pytest、tests、test_target_feature、test_regression

## 1. 任务

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

## 2. 适用规格（来源：seekdb 全文检索）

### SPEC-003 订单列表：按状态筛选（本任务新增）

- 来源：`sample-task/specs/SPEC-003-filter.md`（相似度得分 4.000）
- 规格 ID：SPEC-002, SPEC-003, SPEC-004

```text
# SPEC-003 订单列表：按状态筛选（本任务新增）
- 规格 ID：SPEC-003
- 类型：新增需求（本任务要实现）
- 关联代码：`sample-app/order_service/orders.py` → `list_orders`
- 关联测试：`sample-app/tests/test_target_feature.py` 中的筛选相关用例
## 需求
```

### SPEC-004 订单列表：分页（本任务新增）

- 来源：`sample-task/specs/SPEC-004-pagination.md`（相似度得分 4.000）
- 规格 ID：SPEC-002, SPEC-003, SPEC-004

```text
# SPEC-004 订单列表：分页（本任务新增）
- 规格 ID：SPEC-004
- 类型：新增需求（本任务要实现）
- 关联代码：`sample-app/order_service/orders.py` → `list_orders`
- 关联测试：`sample-app/tests/test_target_feature.py` 中分页相关用例
## 需求
```

### SPEC-005 订单服务其他既有行为（回归约束）

- 来源：`sample-task/specs/SPEC-005-compatibility.md`（相似度得分 4.000）
- 规格 ID：SPEC-005

```text
# SPEC-005 订单服务其他既有行为（回归约束）
- 规格 ID：SPEC-005
- 类型：既有行为（回归约束，不得破坏）
- 关联代码：`sample-app/order_service/orders.py` → `create_order` / `advance_status` / `summarize_orders`
- 关联测试：`sample-app/tests/test_regression.py`
## 需求
```

### SPEC-001 订单创建（既有行为，必须保持）

- 来源：`sample-task/specs/SPEC-001-create.md`（相似度得分 4.000）
- 规格 ID：SPEC-001, SPEC-005

```text
# SPEC-001 订单创建（既有行为，必须保持）
- 规格 ID：SPEC-001
- 类型：既有行为（回归约束）
- 关联代码：`sample-app/order_service/orders.py` → `create_order` / `VALID_STATUSES`
- 关联测试：`sample-app/tests/test_regression.py` 中创建相关用例
## 需求
```

### SPEC-002 订单列表：默认查询（既有行为，必须保持）

- 来源：`sample-task/specs/SPEC-002-list-default.md`（相似度得分 4.000）
- 规格 ID：SPEC-002, SPEC-003, SPEC-004

```text
# SPEC-002 订单列表：默认查询（既有行为，必须保持）
- 规格 ID：SPEC-002
- 类型：既有行为（回归约束）
- 关联代码：`sample-app/order_service/orders.py` → `list_orders`
- 关联测试：`sample-app/tests/test_regression.py::test_list_orders_default_returns_all_in_creation_order`
## 需求
```

## 3. 需要修改的代码（来源：seekdb 全文检索）

- `sample-app/order_service/orders.py`：符号 Order, create_order, list_orders, advance_status, summarize_orders

```text
"""订单服务示例业务代码（SDD 上下文管理系统的“被修改对象”）。
对应规格见 ``sample-task/specs/``。本文件是**修改前**的初始版本：
``list_orders`` 尚未实现 SPEC-003（按状态筛选）与 SPEC-004（分页），
其余函数提供题目要求的“原有行为”，修改后必须保持不变（SPEC-005）。
"""
from __future__ import annotations
```

- `sample-app/order_service/__init__.py`：符号 （无）

```text
"""订单服务示例包。"""
from .orders import (
ALLOWED_TRANSITIONS,
VALID_STATUSES,
Order,
advance_status,
```

## 4. 验证测试（功能测试 + 回归测试）

### 目标功能测试（本次修改后必须通过）
- `sample-app/tests/test_target_feature.py`

### 回归测试（修改前后都必须通过）
- `sample-app/tests/test_regression.py`

## 5. 任务状态（PowerContext）

- 状态来源：已从 PowerContext 读取任务状态
- Scope：`scp_328rmnb7f6rgzk1t5fh8zsqtay`，最新 revision：1
- 已完成：['锁定任务与适用规格：SPEC-001 ~ SPEC-005 已导入 seekdb 并可检索', '上下文模块已生成任务上下文包（规格 / 代码 / 测试 / 任务状态）']
- 待办：['把上下文包交给使用 MiniMax 的开发助手，修改 sample-app/order_service/orders.py 的 list_orders', '运行目标功能测试与回归测试，确认修改前失败、修改后通过', '保存验证结果到 PowerContext，并在模块重启后读取复用']
- 已有验证结果：[]

## 6. 给开发助手的执行要求

- 只修改 `sample-app/order_service/orders.py` 中 `list_orders` 相关实现；
- 必须满足上面列出的适用规格，且保持所有既有行为（回归测试通过）；
- 不要修改测试文件、不要删除断言或跳过测试；
- 修改后运行 `pytest sample-app/tests/test_target_feature.py` 和 `pytest sample-app/tests/test_regression.py`。

