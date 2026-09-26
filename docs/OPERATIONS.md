# 运行、网站接入与维护

## 运行模型

一个主进程、一个 Uvicorn worker；BTC 和美股各有独立采集器及内存缓存。网页访客共用缓存。不需要数据库，也不依赖 GPT。现有 Windows 预览和目标 Linux 服务器是两套独立环境；不能把 Windows `.venv` 复制到 Linux。

## 配置

Python 从操作系统环境变量读取配置，不会自动读取 `.env`。`.env.example` 为 Docker Compose 插值准备，复制到 `.env` 后再改实际值。不要提交真实 `.env`。

| 变量 | 默认值 / 含义 |
| --- | --- |
| `OPTIONS_HOST` | `127.0.0.1`；容器镜像内为 `0.0.0.0` |
| `OPTIONS_PORT` | `8780`；Compose 的同名变量控制主机端口，容器内保持 8780 |
| `OPTIONS_BASE_PATH` | 空；网站子路径示例 `/options`，末尾不加 `/` |
| `OPTIONS_ALLOWED_HOSTS` | `127.0.0.1,localhost`；逗号分隔主机名，不含协议/端口/路径 |
| `OPTIONS_APP_ROOT` | 源码推导的项目根目录，包含 web 和 content |
| `OPTIONS_DATA_DIR` | `<项目>/content`，说明 JSON 目录 |
| `OPTIONS_RUNTIME_DIR` | `<项目>/runtime`，进程锁和本机运行资料 |
| `OPTIONS_LOG_DIR` | `<runtime>/logs` |
| `OPTIONS_COLLECTOR_ENABLED` | `true`；false 仅适合测试/离线检查，不代表共享旧实例的行情 |
| `OPTIONS_US_DATA_DIR` | `<runtime>/us-equities/data`，真实自选和个人说明，不提交 |
| `OPTIONS_US_COLLECTOR_ENABLED` | `true`；仅开关美股采集 |
| `OPTIONS_BITCOIN_COLLECTOR_ENABLED` | `true`；仅开关 BTC 采集 |
| `OPTIONS_BITCOIN_PROVIDER` | `binance`；选择已注册的 BTC 数据源，未知值使该市场报配置错误，不换源 |
| `OPTIONS_US_EQUITIES_PROVIDER` | `alpaca`；选择已注册的美股数据源，未知值使该市场报配置错误，不换源 |
| `ALPACA_API_KEY` / `ALPACA_API_SECRET` | 成对注入；未设置时 Windows 尝试当前用户 DPAPI，其他系统待配置 |
| `OPTIONS_FORWARDED_HEADERS` | `false`；启用时 CLI 仅信任来自 127.0.0.1 的代理头 |

启动参数 `--host`、`--port`、`--base-path` 优先于环境变量。`--open` 打开本机浏览器。不要在生产使用自动重载或多个 worker。

监控使用 `/healthz` 判断进程是否响应，使用 `/api/v1/status` 分别查看各市场的运行与数据健康；`/readyz` 继续保留原 BTC 就绪语义。美股没有活跃浏览器租约时不会持续抓取所有自选股票，`no_active` 不等于数据源故障。修改供应商配置需要重启，旧内存快照不会转成新来源的备用数据。

## 网站集成方式

推荐：现有网站“期权面板”按钮链接到 `/options/`，进入二级市场模块入口。BTC 的桌面/手机地址分别为 `/options/bitcoin/desktop/`、`/options/bitcoin/mobile/`。

也可以在同源页面中用 iframe 显示某个页面，或者网站自己的 React/Vue 组件直接读取 v1 API。跨域 iframe 默认会被 `frame-ancestors 'self'` 拦截；优先通过网站同源代理接入。这里没有开放任意跨域访问。

**子路径策略是保留前缀转发**：Python 真正注册 `/options/...` 路由；Nginx `proxy_pass http://127.0.0.1:8780;` 不带尾斜线，不剥除 `/options`。不要同时设置 Uvicorn `root_path` 或再做一次前缀剥除。参见 [Nginx proxy_pass 语义](https://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_pass)。

## 容器部署示例（目标服务器由接手团队执行）

在项目根目录的 Linux shell：

```sh
cp .env.example .env
# 编辑 .env：把 OPTIONS_ALLOWED_HOSTS 中的示例域名换成真实网站域名。
docker compose config
docker compose up -d --build
curl -f http://127.0.0.1:8780/options/healthz
curl -f http://127.0.0.1:8780/options/readyz
docker compose logs --tail 100
```

将 `deploy/nginx-location.conf` 合并进现有 HTTPS server 块，团队检查 Nginx 配置后重载。证书、实际域名、反代限流和网站身份系统由现有网站负责。这份示例不会自动配置它们。

在具备本项目 Python 环境的验证机器上，运行 `python scripts/verify_live.py --url http://127.0.0.1:8780/options`；若验证部署到远端的网址，替换整段 URL，但保留实际子路径。不能用脚本默认根路径去检查 Compose 默认的 `/options` 服务。

Compose 仅向主机 127.0.0.1 映射端口；镜像使用 UID 10001，根文件系统只读，runtime 用命名卷。单实例 `restart: unless-stopped`；进程退出会重启，**Docker unhealthy 本身不会自动重启进程**。日志驱动限制大小；采集日志另行轮转。

存活检测用 `/healthz`，不要因上游短暂断线、`/readyz` 503 而持续重启应用。首次启动需要抓取完整目录与行情，readyz 暂时 503 是正常的。TLS 通常在反向代理终止。[FastAPI 部署文档](https://fastapi.tiangolo.com/deployment/concepts/)

本地未安装 Docker，因此 Docker/Linux 配置是待目标环境验收的交付件，不能把 Windows 测试结果当作 Linux 实机测试。基础镜像使用 `python:3.13-slim`，团队构建验收后可进一步固定镜像 digest。

## Windows 局域网预览

在项目根目录 PowerShell 中，将地址替换为这台电脑当前的局域网 IP：

```powershell
$env:OPTIONS_ALLOWED_HOSTS = '127.0.0.1,localhost,192.168.2.2'
.\scripts\start.ps1 --host 0.0.0.0 --port 8780
```

同一网络手机访问 `http://电脑局域网IP:8780/bitcoin/mobile/`。如防火墙阻止，由电脑管理员按实际私有网络配置。该示例不会自动添加防火墙规则，也不是公网发布方式。本任务不使用此示例修改当前监听；局域网发布由独立任务维护。

## 日志与排错

日志：`runtime/logs/options-panel.log`，每行 JSON，有 UTC `time`、`event`、`level`、请求路径、耗时、重试/恢复结果等。单文件 5 MiB，最多 5 个备份；日志目录不可写时退回控制台。记录不包含行情响应全文。Uvicorn 访问日志由托管环境保管。

| 现象 | 检查 / 处理 |
| --- | --- |
| 页面连不上，healthz 也失败 | 进程、端口占用、反代 upstream；查看启动控制台 |
| 页面可开但 waiting / readyz 503 | 首次抓取未完成或行情过期；查 market/catalog 日志，不反复手动刷新制造请求 |
| SSL UNEXPECTED_EOF | 上游/中间网络连接提前断开；内置有限重试及退避，保留缓存；不要关闭证书校验 |
| HTTP 429 | 不立即重试该请求，等待后台退避；检查是否误启多个实例及上游限制 |
| 概率不可用但年化更新 | 检查 mark_warning；不会用旧 IV 混合新指数 |
| Invalid host header / HTTP 400 | 把实际 Host 加到白名单，反代传正确 Host；不要直接改成 `*` |
| 页面样式/JS 404 | 核对基路径，确认反代保留前缀、页面尾斜线和 web 目录都存在 |
| runtime collector already active | 同一运行目录已有采集实例；不要删运行中的锁文件，先找管理该进程的托管服务 |
| 本机 CMD / 旧 PowerShell 提示需要提升权限 | 可能设置了“以管理员运行”的系统兼容选项；本项目本身不需要管理员权限，可在已有 PowerShell 7 中运行 `scripts/start.ps1`。不要为启动看板修改系统权限或关闭防护 |
| 浏览器显示旧界面 | 重新加载；HTML/JS 没有长期缓存，检查 CDN 是否额外缓存了页面 |

监控至少应覆盖进程存活、readyz、数据年龄、连续失败、刷新耗时和磁盘空间。真实负载压测由上线团队在目标网络执行。

## 更新与回滚

1. 保存一个经过验收的源码版本/镜像标签和说明内容；在另一个测试运行目录/端口做迁移验证。
2. 运行全部自动测试、前端检查和三轮真实行情核对。
3. 停止旧的这一服务实例，再替换/启动新的单实例。不要滚动扩成两个采集副本。
4. 检查 healthz、readyz、PC/手机、错误日志。失败则退回上一版源码/镜像；不要删除运行数据卷。

缓存重启后重新获取；说明文件需随版本保留。扩展多个服务器时，先设计外置共享快照及单独采集职责，当前文件锁不解决跨机器协调。

## 美股部署补充

详见 [US-EQUITIES.md](US-EQUITIES.md)。Compose 已声明可选的 Alpaca 环境透传；将两个变量成对配置在宿主安全环境或不提交的 `.env` 中，重新创建容器后生效。不要在命令参数、日志或源码中填写凭据。默认不配置时 BTC 仍可用。DPAPI 文件不能复制给 Linux 使用。

`/readyz` 保持 BTC 兼容语义；单独监控美股 `/api/v1/us-equities/health` 的 `status/collector_running` 和快照的 `fetch_health/fetched_age_seconds`。本机管理不要加入 Nginx upstream、容器公网端口或公开路由。实例默认说明和自选可被所有获准访问主面板的访客读取；公网环境应使用经过审核的独立数据目录，必要时由宿主网站加身份认证。Alpaca 行情再分发授权未在本轮落实。
