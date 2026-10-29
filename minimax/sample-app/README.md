# 订单服务示例工程（被 SDD 上下文模块修改对象）

这是一个可运行、带测试的小型 Python 业务工程，用于 SDD 上下文管理系统的验证样例：
「给订单列表查询增加按状态筛选与分页」。

## 结构

```
sample-app/
├── order_service/
│   ├── __init__.py
│   └── orders.py          # 业务代码（create_order / list_orders / advance_status / summarize_orders）
├── tests/
│   ├── test_regression.py # 既有行为回归测试（修改前后都必须通过）
│   └── test_target_feature.py # 目标功能测试（修改前失败，修改后通过）
└── pyproject.toml         # pytest 配置
```

## 运行测试

```bash
cd sample-app
python -m pytest tests/test_regression.py -q
python -m pytest tests/test_target_feature.py -q
```

修改前：`test_target_feature.py` 应有 8 条失败（2 条默认行为用例通过），`test_regression.py`
16 条全部通过；修改后两组测试全部通过。详细日志见 `../logs/`。
