# 语言选择与长期运行

## 结论

当前适合保留 Python，把临时本地 HTTP 服务迁移到 FastAPI + Uvicorn。不存在脱离负载与团队能力的“最稳定语言”。本项目主要是周期性外部请求、少量计算、共享快照和表格展示，没有测量证据支持为了性能整体改写成 Node.js 或 Go。

对朋友可以这样描述：**后端 Python 3，使用 FastAPI 和 Uvicorn；前端原生 HTML、CSS、JavaScript；前后端通过只读 JSON API 连接，部署支持子路径与 Docker。**

## 为什么改服务层，而不重写业务

Python 官方不建议把 `http.server` 用于生产，它只提供基本安全检查；这针对原本地服务方式，不是对 Python 语言的否定。[Python 官方文档](https://docs.python.org/3/library/http.server.html)

FastAPI 文档列出的运行要点包括 HTTPS、进程启动/重启、内存和多进程。普通并发请求可以由一个服务进程处理；多个进程通常各有自己的内存。因此本项目采用单 worker 共享缓存，避免每个 worker 重复采集。这是结合项目结构作出的工程判断。[FastAPI 部署概念](https://fastapi.tiangolo.com/deployment/concepts/)

应用通过 lifespan 管理采集线程的启动与清理。[FastAPI Lifespan](https://fastapi.tiangolo.com/advanced/events/)

## 可选方案的取舍

| 方案 | 适用条件 | 此项目选择 |
| --- | --- | --- |
| Python / FastAPI | 团队接受 Python，金融计算与数据适配较多 | 已实施，保留验证过的算法 |
| Node.js / TypeScript 后端 | 网站团队主要使用 TypeScript，希望统一维护语言 | 可由团队采用现有 API/测试契约迁移；本次没有必要重写 |
| Go 后端 | 实测出现 Python CPU、内存或大量连接瓶颈，团队能维护 Go | 先量化瓶颈，不能仅凭语言推断收益 |
| React / Vue 前端 | 网站已有组件系统、路由、权限和设计规范 | 可消费本项目 API；和是否使用 Python 后端无冲突 |

这些是技术适用性判断，不是跨语言性能测试结论。没有承诺支持多少同时在线用户。

## 稳定性主要依赖什么

- 唯一采集器、有界超时/重试/并发、失败退避，避免访客数量决定对外请求数量。
- 冻结的计算结果、完整快照提交、明确的过期标志。
- 依赖锁定、回归测试、发布前后健康检查、可回滚版本。
- HTTPS 反向代理、进程托管、日志轮转和告警。
- 上线后记录真实负载，再决定是否增加 Redis、独立采集服务或新技术栈。

公开站点仍需在其目标服务器完成网络可达性、资源容量、监控和数据展示许可的核验。这次交付不等于已经完成公网部署。资料核验日期：2026-09-26。
