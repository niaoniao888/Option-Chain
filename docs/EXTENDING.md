# 增加市场或数据源

## 替换现有市场的数据源

在 `providers/registry.py` 注册 `ProviderBinding`，提供 market_id、provider_id、显示名和非空 adapter。BTC adapter 实现目录、报价、指数、服务器时间、OI、mark 接口；US adapter 实现 fetch，并可提供 `configuration_status()`。默认仍为 Binance/Alpaca；未知或缺失适配器只使该市场 unavailable，不换源。

provider 必须保留市场原有 Runtime、刷新策略和领域计算，并由 adapter 明确提供 `source_name`；BTC 可另提供面向快照的 `snapshot_source`，US 可提供等待首轮数据时的 `pending_source_delay_label`。不得用默认 Binance/Alpaca 名称标记替代来源，也不得把已有代次重新贴成另一 provider。测试至少覆盖 falsey adapter、真实一次刷新、HTTP payload 与 envelope/cache 的 provider/source 身份一致、缓存键隔离，以及配置状态不依赖默认供应商凭据。

## 增加第三市场

1. 定义 `MarketDescriptor`：稳定 market_id、provider、默认 instrument、PC/手机路径、capabilities。
2. 实现 `MarketRuntime`：start、stop、health、snapshot_envelope。计算、时区、交易日历和资格保留市场语义。
   若市场使用单采集线程，组合 `CollectorSupervisor(make_thread, signal_stop, lock_path, join_timeout)`；线程自身继续实现该市场的 run loop。不得在新 Runtime 再复制锁、超时和重复启动处理。
3. 建立 `MarketRegistration`；特色 API 用 route_installer，页面用 StaticPageConfig 指向 `web/app/index.html` 与 ESM 白名单。
4. 前端实现 adapter 并调用 `registerMarketAdapter`。adapter 提供标题、列、精度、expiry 解析/显示、合同 ID、资格、排序值、收益/概率展示、状态和 snapshotVersion。
5. 模块导航来自 `/api/v1/modules`，只有同时注册的前端 adapter 才显示。所有动态标签使用 textContent 或 escapeHtml。
6. 增加实际 GET snapshot/health/page 测试，以及通过共用 Dashboard 的浏览器 fixture；只注册卡片或返回 404 不算完成。

前端 adapter 必须在 `web/app/markets/registry.js` 以静态 ESM import 注册，并把新增模块文件加入后端 `APP_ASSETS` 白名单。不要从市场标签、查询参数或运行时响应拼接脚本 URL。装配时会同时核对 registration、runtime descriptor 与 provider binding 的 market/provider 身份；不一致只隔离该市场，不能把一个来源的 Runtime 重新标记为另一个来源。

前端 adapter 不复制轮询、存储、菜单、分页或表格，不在浏览器重算后台金融指标。无明确 version 的市场必须让可见值进入 fallback signature；有 version 的市场必须在任何金融快照变化时推进 version。浏览器验收应让测试 registry 覆盖全部已注册市场与模式，从第三市场实际 URL 启动，经 `main.js` bootstrap 读取真实 page/snapshot/health，再点击已有市场并返回第三市场；至少再覆盖第三市场手机入口。fixture 只能由隔离测试服务注册，不能进入生产 registry。

## 必须重新核实

每个新市场都要独立核实交易日/DST、提前收市、到期截止、乘数、调整合约、分红、延迟源、Bid 规则、概率参数及休市冻结口径。BTC 的 24/7、USDT 和 30 分钟结算条件不得套用到其他市场。
