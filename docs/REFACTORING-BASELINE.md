# 统一平台后端重构基线

## 范围

本阶段只整理后端装配、路由、市场注册、快照包装、短缓存、进程锁和生命周期。BTC、US 的 provider 解析、刷新策略、领域计算、快照 payload、管理边界、凭据目录和现有网页均保持原实现。

## 冻结契约

- 保留 `/api/snapshot`、`/api/health`、`/api/options-guide` 及全部 `/api/v1/bitcoin/*`、`/api/v1/us-equities/*` 路径。
- 保留 US 唯一 symbol、自选校验、`if_version`、`client_id`、`active`、`activity_seq`、租约容量 429 与 `Retry-After: 15`。
- 保留 `/healthz` 和以 BTC 新鲜完整行情为准的 `/readyz` 语义。
- 新增只读 `/api/v1/status`，逐市场报告初始化、启动、停止和数据 health；公共错误只报告异常类型，不返回异常正文。

## 新基础设施

- `app_factory.py` 只负责 FastAPI 工厂和公共中间件；`routes/` 分离静态、市场和系统路由；`assembly.py` 根据注册表建立运行时。
- `MarketDescriptor` 声明市场、默认 provider、页面和能力；`SnapshotEnvelope` 在不改变原 payload 的前提下补充市场、来源、标的、版本、接收时间、计算时间和状态。
- `MarketRegistry` 的工厂只接收通用 `RuntimeContext`；BTC 旧 `DashboardState` 注入封装在 BTC 工厂的兼容字段中，新市场不依赖 BTC 类型。注册项声明 API profile、静态页面目录和可选特色路由安装器；第三市场无需修改应用核心即可获得 lifecycle、模块发现、通用 snapshot/health 和注册页面。
- `ProviderRegistry` 按 market/provider 两级注册数据源工厂。BTC 的 `Refresher` 只保留调度、退避与状态提交，Binance EAPI 路径和解析封装在 `BinanceOptionsProvider`；同一市场替换 provider 时复用 `BitcoinRuntime` 与 `Refresher`。运行时 descriptor、快照 envelope 和缓存键均保留来源身份。未知环境 provider 会使对应市场初始化失败，不会回退到默认来源，并在模块发现中显示配置的 provider 与 `unavailable`。
- `SnapshotResponseCache` 以 market/provider/instrument 为键，默认最多 256 项，并在访问时清理 TTL 过期项。
- `ProcessLock` 移到共用 runtime 模块；旧导入路径继续兼容。生命周期逐市场隔离初始化、启动和停止异常。停止超时的线程及锁继续保留，禁止同一 runtime 重复启动采集线程。

## 验证基线

重构前运行 `python -m unittest discover -s tests`：162 项通过。新增测试覆盖缓存隔离与有界淘汰、envelope、第三市场、替代 provider、未知 provider、初始化失败脱敏隔离、停止异常隔离和停止超时不重复启动。最终结果以任务交付记录为准。
