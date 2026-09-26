# 增加市场或数据源

## 替换现有市场的数据源

在 `providers/registry.py` 注册 `ProviderBinding`，提供 market_id、provider_id、显示名和非空 adapter。BTC adapter 实现目录、报价、指数、服务器时间、OI、mark 接口；US adapter 实现 fetch，并可提供 `configuration_status()`。默认仍为 Binance/Alpaca；未知或缺失适配器只使该市场 unavailable，不换源。

provider 必须保留市场原有 Runtime、刷新策略和领域计算。测试至少覆盖 falsey adapter、真实一次刷新、envelope provider 身份、缓存键隔离，以及配置状态不依赖默认供应商凭据。

## 增加第三市场

1. 定义 `MarketDescriptor`：稳定 market_id、provider、默认 instrument、PC/手机路径、capabilities。
2. 实现 `MarketRuntime`：start、stop、health、snapshot_envelope。计算、时区、交易日历和资格保留市场语义。
3. 建立 `MarketRegistration`；特色 API 用 route_installer，页面用 StaticPageConfig 指向 `web/app/index.html` 与 ESM 白名单。
4. 前端实现 adapter 并调用 `registerMarketAdapter`。adapter 提供标题、列、精度、expiry 解析/显示、合同 ID、资格、排序值、收益/概率展示、状态和 snapshotVersion。
5. 模块导航来自 `/api/v1/modules`，只有同时注册的前端 adapter 才显示。所有动态标签使用 textContent 或 escapeHtml。
6. 增加实际 GET snapshot/health/page 测试，以及通过共用 Dashboard 的浏览器 fixture；只注册卡片或返回 404 不算完成。

前端 adapter 不复制轮询、存储、菜单、分页或表格，不在浏览器重算后台金融指标。无明确 version 的市场必须让可见值进入 fallback signature；有 version 的市场必须在任何金融快照变化时推进 version。

## 必须重新核实

每个新市场都要独立核实交易日/DST、提前收市、到期截止、乘数、调整合约、分红、延迟源、Bid 规则、概率参数及休市冻结口径。BTC 的 24/7、USDT 和 30 分钟结算条件不得套用到其他市场。
