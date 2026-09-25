# 如何增加更多市场模块

当前已实现 BTC 与 Alpaca 美股模块。嘉信尚未接入；后续市场可参照 `us_equities/` 的独立适配、计算、缓存、状态和测试边界。

## 后续市场的增加步骤

1. **确定数据契约**：来源、授权/实时或延迟标志、股票报价、Call/Put、到期与交易截止时间、Bid/Ask、合约单位、调整合约及无报价规则。
2. 在 `providers/` 新增该供应商适配，如 `us_market.py`。只负责请求、错误分类、解析；不在网页或 API 请求线程里调用供应商。
3. 新建 `modules/us_equities.py` 模块上下文以及独立的采集/状态实现。当前 BTC 的 `runtime/refresher.py`、`snapshot.py` 包含 Binance 和 BTC 约定，不应改名后直接套给美股。
4. 为 `/api/v1/us-equities/...` 注册独立路由与状态。每个市场有自己的数据时间、降级/过期状态；一个市场失败不能清空另一个市场。
5. 增加该模块页面，在 `modules/registry.py` 加元数据。入口页会读取登记表显示新卡片，但服务和页面必须已真实存在，不能只加一个不可用链接。
6. 补数学、交易日历、数据异常、API、UI、回归测试及模块说明。通过后才将状态登记为可用。

以下是旧扩展设计示意；实际美股模块集中于 `src/options_panel/us_equities/`，请勿重复新建另一套：

```text
src/options_panel/providers/us_market.py
src/options_panel/modules/us_equities.py
src/options_panel/runtime/us_snapshot.py
src/options_panel/runtime/us_refresher.py
web/us-equities/
tests/test_us_*.py
```

模块增多后，可将 `api.py` 拆成 `APIRouter` 并形成正式的 `Module` 协议；当前注册表是清晰的扩展入口，不是动态插件系统。

## 哪些可复用，哪些必须重新核实

可复用：数值有限性校验、时间差转换、只读 API、版本化接口、日志、短响应缓存、前端格式/主题、分页与选择持久化的模式。

必须重新核实：交易日与时区/DST、提前收市、到期与行权截止时刻、现金/实物结算、指数/股票价的一致性、合约乘数、调整合约、分红、概率模型参数、延迟报价、休市后收益的冻结时间。美股不能直接沿用“BTC 24/7、USDT、30 分钟结算窗口”的条件。

公共字段优先统一 `module_id/provider/as_of/received_at/status` 等语义，但不要在来源不明时把延迟行情改称实时。每个市场保留自己的计算版本和不可用原因。

## 网站团队选择

若网站已有 TypeScript 组件体系，可以继续保留 Python 数据服务，用网站组件渲染二级模块。需要账号权限时接入现有网站身份系统；不要通过浏览器 IP、localhost 或隐藏按钮来判断管理员。说明的公开读取与后台编辑应是不同的权限边界。
