# 只读 API 契约 v1

以下路径相对于 `OPTIONS_BASE_PATH`。默认基路径为空；设为 `/options` 时，例如快照 URL 为 `/options/api/v1/bitcoin/snapshot`。响应为 UTF-8 JSON；没有密钥参数。现有前端仍使用兼容别名，新接入使用 v1 路径。

| GET 路径 | 返回 / 状态 |
| --- | --- |
| `/api/v1/modules` | 已实现模块的元数据数组及包含基路径的页面链接 |
| `/api/v1/bitcoin/snapshot` | 行情快照；初始化时允许空值/空数组，检查 `status` |
| `/api/v1/bitcoin/health` | 数据状态、年龄、错误摘要 |
| `/api/v1/bitcoin/options-guide` | 说明 JSON；文件不可用时 503 |
| `/healthz` | 进程可响应时 200；用于存活检查 |
| `/readyz` | 初次数据就绪且未过期时 200，否则 503 |
| `/api/snapshot`、`/api/health`、`/api/options-guide` | 上述三个 BTC 接口的兼容别名，共用同一状态 |

POST / PUT / PATCH / DELETE 均返回 405，不提供写接口。没有开启跨域 CORS。静态资源采用白名单路由，不把整个项目目录映射到网站。

## 快照顶层

| 字段 | 类型 / 说明 |
| --- | --- |
| `app`, `source`, `underlying`, `currency` | 应用标识、来源、BTCUSDT、USDT |
| `index_price` | number 或 null；未取整指数 |
| `market_generation_ms` | number 或 null；最近成功批次的计算时间，UTC Unix 毫秒 |
| `fetched_at`, `catalog_fetched_at` | UTC ISO 字符串或 null；本机完成获取时间 |
| `server_time`, `server_time_ms` | 当前估算的服务器时间；服务端依据单调时钟推进 |
| `next_refresh_seconds`, `next_catalog_refresh_seconds` | 下次计划尝试的秒数；失败退避时不一定是 60 |
| `status` | 下述状态对象 |
| `contracts` | 合约数组；不要假定只有一个到期日或每个行权价都有双侧 |

状态对象字段：`app`, `version`, `status`（`healthy` / `degraded` / `error`），`stale`，`age_seconds`，`market_error`，`catalog_error`，`mark_warning`。正常值不等于报价必能成交。

- 未首次成功：`error`；没有伪造或示例行情补齐。
- 失败但有缓存：`degraded`，保留 `fetched_at` / `market_generation_ms`。
- 距成功行情至少 120 秒或无行情：`stale=true`。
- `/readyz` 允许主行情新鲜但 mark 参数受损的 `degraded` 状态；需完整概率的消费者应同时检查 `mark_warning`。

## 合约字段

| 字段组 | 说明 |
| --- | --- |
| `symbol`, `side`, `strike`, `unit`, `status`, `expiry_ms` | 合约代码、CALL/PUT、行权价、合约单位、交易状态、到期毫秒 |
| `bid`, `ask`, `last`, `last_trade_time_ms` | 报价及最后成交时间；最后成交时间**不是**盘口更新时间 |
| `open_interest`, `open_interest_time_ms` | 持仓量与其来源时间；0 有特殊显示规则，未知不等于 0 |
| `intrinsic_value`, `time_value`, `time_value_status` | 内在价值、买价时间价值及 positive / zero / negative / unavailable / expired |
| `capital_base`, `calculation_index_price`, `remaining_years` | 收益计算基准、同轮原始指数、冻结剩余年数 |
| `period_return_pct`, `annualized_pct` | 单期收益率和年化，百分数值：6.08 表示 6.08%，不是 0.0608 |
| `annualized_basis` | `time_value_on_spot`（Call）或 `time_value_on_strike`（Put） |
| `annualized_calculated_at_ms`, `annualized_unavailable_reason` | 收益计算时间、不可用原因 |
| `mark_time_value`, `mark_period_return_pct`, `mark_annualized_pct`, `mark_annualized_calculated_at_ms` | 非正 Bid 时间价值时的同轮 Mark 参考结果，不可当成交报价 |
| `mark_iv`, `risk_free_interest`, `delta`, `mark_price` | 模型参数和参考值。IV/利率是比例，例如 0.5 表示 50% |
| `exercise_probability_pct`, `probability_calculated_at_ms` | 模型概率百分数及其冻结计算时间 |
| `exercise_probability_unavailable_reason`, `probability_display_state` | 概率原因及 normal / settling / unavailable / expired |
| `remaining_seconds` | 读快照时剩余秒数；不能用于重新计算已冻结的收益 |
| `moneyness`, `atm_tolerance` | ITM/ATM/OTM 和判断容差，供兼容和核验 |

收益不可用原因包括 `zero_open_interest`, `expired`, `invalid_bid`, `invalid_index`, `invalid_contract`, `nonpositive_time_value`, `market_generation_unavailable`。概率原因见 `exercise_probability` 与 `snapshot` 实现，包括 mark/参数缺失、到期等。客户端应保留未知原因字符串，不因将来新增原因而崩溃。

**null 不是 0。** `probability_display_state=settling` 时即使接口保留一个冻结概率数值，页面也要显示结算中。到期后结果不可用。单位与显示规则见 [计算契约](CALCULATIONS.md)。

## 缓存与前端约定

快照响应短缓存 1 秒并支持 GZip。主行情代次由 `market_generation_ms` 标识；目录代次由 `catalog_fetched_at` 标识。更新倒计时/连接状态可以轻量渲染，不要每秒替换整个表格 DOM。保持选择、文本复制和滚动位置的逻辑位于各前端 JS。

服务重启后内存清空。数据失败时 API 仍可能返回 200 的旧快照，所以调用方必须检查 `status.stale` 和 `fetched_at`，不能只看 HTTP 200。

说明结构为 `{revision, updated_at, sections: [{id, title, topics: [{id, title, body}]}]}`。正文通过安全文本渲染，不执行任意 HTML。前端读说明；维护人员在仓库改 JSON，经测试后发布。
