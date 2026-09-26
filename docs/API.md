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

## 美股 v1（2.1.0）

所有路径可加 OPTIONS_BASE_PATH。主服务全部只读，POST/PUT/DELETE 均返回 405。

| GET | 返回 |
| --- | --- |
| `/api/v1/us-equities/health` | configured、collector_running、status、refresh_policy、数据汇总、writable=false |
| `/api/v1/us-equities/watchlist` | symbols、revision |
| `/api/v1/us-equities/options-guide` | sections、revision、updated_at |
| `/api/v1/us-equities/snapshot?symbol=GOOG` | 独立美股快照 |

快照必须提供唯一 symbol 且属于该实例自选；if_version 可传上一版本。版本不变时 unchanged=true 且不发送 contracts，前端必须保留原合约数组，并按新状态更新过期/排行资格。client_id 为每个页面独立的 1–64 位标识；active=1 续租、active=0 释放；activity_seq 单调增加以抵抗乱序。最多跟踪 2048 个短期会话，超限新会话返回 429 和 Retry-After:15。legacy 与 client_id 请求共用最多 128 个活跃 symbol 的资源上限；刷新队列不会超过该上限，闲置缓存保留最近 10 个 symbol。128 是资源保护值，不承诺 128 个 symbol 都能在每个 60 秒周期内完成刷新。此容量保护不替代公开网站反代限流。

美股字段包含 underlying_price、market_status、quote_time、fetched_at、calculated_at、fetch_health、mode、snapshot_version。合约字段以 us_equities/model.py 为准，包含 annualized_pct、period_return_pct、capital_base、time_value、calculation_basis_utc、exercise_probability_pct、probability_reason、ranking_eligible、close_reference_eligible 等。不得把 BTC index_price/markIV 等字段强行映射成同一含义。

美股健康接口及 `/api/v1/status` 的公开 Runtime 摘要可包含 `data_status`（`no_active` / `waiting` / `partial` / `healthy` / `failed` / `degraded` / `stale`）、active/cache/queued/inflight/waiting symbol 数、failure_count、data_age_seconds 和 contract_count。这些字段只汇总顶层元数据，不生成快照或复制合约。`no_active` 表示当前没有访问租约，不等于采集故障；`partial` 表示部分活跃标的已有成功快照、其余仍在首轮等待。存在 `partial`、刷新失败或过期时 Runtime `status` 降级。原接口状态码和既有字段不变。

本机管理 API 在另一回环进程，路径为 /api/watchlist 和 /api/options-guide。全部管理 GET 也需 Authorization:Bearer；POST/DELETE 自选与 PUT 说明需 If-Match、同源 Origin/Host 和 JSON Content-Type。409 表示版本冲突，不可直接重试覆盖。自选最多新增到 128 个，达到上限后新增返回 429；历史文件即使已超过上限仍可读取并删除，以便安全缩减，不能通过继续新增扩大。主服务不注册这些写路由，管理静态资源也不可从主服务读取。
