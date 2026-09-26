# 架构与代码导航

## 应用装配

`app_factory.py` 创建 FastAPI 应用，`assembly.py` 根据 `MarketRegistry` 和 `ProviderRegistry` 装配运行时，`routes/` 分别安装市场 API、旧兼容别名和静态页面。初始化失败记录异常类型并只隔离对应市场；`/api/v1/status` 只返回允许公开的健康字段。

`MarketDescriptor` 声明 market/provider/instrument、页面路径和能力；`SnapshotEnvelope` 保留统一元数据及原市场 payload。短响应缓存键包含 market/provider/instrument，并有 TTL 与容量上限。BTC 旧 v1/别名、US 查询验证与租约、429 Retry-After、`/readyz` 语义保持兼容。

## 数据流与生命周期

BTC 默认 provider 是 BinanceOptionsProvider，Refresher 保留原目录/行情节奏和计算提交顺序。US 默认 provider 是 AlpacaAdapter，MarketService 保留访问租约、公平刷新队列和轻量 unchanged 响应。替代 provider 通过注册表注入现有市场运行时；缺少适配器会使该市场初始化失败，不会静默换回默认源。

RuntimeLifecycle 负责跨市场启停隔离和公开状态；每个 Runtime 内部复用 `CollectorSupervisor` 持有 ProcessLock、线程引用和 15 秒停止等待。BTC 的 Refresher 仍是原线程，US 仍以线程运行 MarketService，各自 run loop、刷新间隔和失败策略没有合并。线程工厂、启动、停止回调或 join 失败不会泄漏或提前释放锁；停止超时或回调异常时，监督器在进程级保留未终止所有者，即使 Runtime 被回收也继续持锁，确认线程结束后由后续 start/stop 安全清理且不保留已结束引用。

BTC `DashboardState` 在首个代次前绑定 provider/source；已有数据不能换成另一来源标签。US `MarketService.health_summary()` 只读取顶层缓存、租约、队列、失败计数和年龄，不复制或重新投影 contracts。无活跃租约时数据状态为 `no_active`，不会因闲置缓存老化使 Runtime 永久异常；部分活跃标的已有数据而另一些仍在首轮等待时为 `partial`，不会误报全部健康。

结构化 JSON 日志轮转，刷新事件包含 market、provider、instrument、耗时、连续失败、数据年龄、队列等待、缓存规模和合约数。公共状态和日志只记录异常类型或布尔状态，不记录异常正文、凭据或带密钥 URL。

## 统一前端

四个旧 URL 均由 `web/app/index.html` 提供：

- `core/`：安全存储、单链 polling、原始/投影模型和格式。
- `components/`：菜单、Dashboard、三视图、排序和分页，不判断市场 ID。
- `markets/`：BTC/US 字段、资格、日期、列、精度和展示适配。
- `styles.css`：BTC ui10 基准的共享响应式样式。

每个请求链支持 AbortController、超时、响应序列防覆盖、hidden 释放/恢复和 429 有界退避。generation/version 未变且可见投影未变化时不替换表格 DOM；剩余时间跨分钟/小时、到期/报价资格边界或金融值改变时更新。选择、复制、菜单交互期间只暂缓确有必要的表格重绘，保护结束后刷新最新结果。

原始 payload 保留，前端不重算年化、单期收益和行权概率。BTC 与 US 的 15 天默认期、结算窗口、close-reference、时区、非标准合约资格等差异都在适配器中。状态存储按 market/provider/instrument/mode 隔离，并只在来源适用时迁移旧键。

## 扩展边界

新增市场需后端注册 descriptor/runtime/provider/static page，并在前端注册 adapter；通用 Dashboard 和 polling 不增加市场分支。管理页独立保留，说明 JSON API/存储仍兼容，但主看板不再加载旧说明或 `web/shared` 页面资产。

当前是单进程内存快照架构。多 worker、多实例和跨机采集锁尚未实现；扩大部署前需分离唯一采集器与共享存储。

## Linux 运维边界

Compose 保持一个服务、一个 worker，容器根文件系统只读，只有 `/app/runtime` 命名卷可写。`scripts/options-panel.sh` 是 Linux 生命周期入口；`options_panel.manage` 只通过现有 WatchlistStore/GuideStore 离线读写个人文档，不装配 Runtime、采集器或 HTTP 路由。`options_panel.runtime_archive` 只归档四个允许的个人数据文件，恢复在停止状态执行并先完成完整校验。
