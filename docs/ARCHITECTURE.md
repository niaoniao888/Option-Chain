# 架构与代码导航

## 应用装配

`app_factory.py` 创建 FastAPI 应用，`assembly.py` 根据 `MarketRegistry` 和 `ProviderRegistry` 装配运行时，`routes/` 分别安装市场 API、旧兼容别名和静态页面。初始化失败记录异常类型并只隔离对应市场；`/api/v1/status` 只返回允许公开的健康字段。

`MarketDescriptor` 声明 market/provider/instrument、页面路径和能力；`SnapshotEnvelope` 保留统一元数据及原市场 payload。短响应缓存键包含 market/provider/instrument，并有 TTL 与容量上限。BTC 旧 v1/别名、US 查询验证与租约、429 Retry-After、`/readyz` 语义保持兼容。

## 数据流与生命周期

BTC 默认 provider 是 BinanceOptionsProvider，Refresher 保留原目录/行情节奏和计算提交顺序。US 默认 provider 是 AlpacaAdapter，MarketService 保留访问租约、公平刷新队列和轻量 unchanged 响应。替代 provider 通过注册表注入现有市场运行时；缺少适配器会使该市场初始化失败，不会静默换回默认源。

RuntimeLifecycle 统一启动、停止和公开状态，ProcessLock 防止同一运行目录出现第二采集所有者。两个市场的线程调度尚未强行合并：BTC Refresher 本身是线程，US runtime 包装 MarketService 线程。停止超时保留线程引用和锁，直到确认线程结束，防止重复启动。

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
