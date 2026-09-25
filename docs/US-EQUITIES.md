# 美股模块配置、迁移和维护

## 入口和来源

| 功能 | 主服务相对路径 |
| --- | --- |
| 桌面 | `/us-equities/desktop/` |
| 手机 | `/us-equities/mobile/` |
| 快照 | `/api/v1/us-equities/snapshot?symbol=AAPL` |
| 自选 / 状态 / 说明 | `/api/v1/us-equities/watchlist`、`health`、`options-guide` |

路径前缀 `/options` 时，以上路径全部加该前缀。当前电脑主服务为 `http://127.0.0.1:8782`；手机路径在本任务仅供电脑预览，实体手机由独立局域网任务提供服务。

数据来自 **Alpaca 股票 IEX / 期权 Indicative**。Indicative 是经过调整的指示性报价，不应当作真实 OPRA 可成交报价。[Alpaca 官方数据说明](https://docs.alpaca.markets/us/docs/historical-option-data)。公开域名上线前另行确认展示授权；[官方说明限制 API 行情再分发](https://alpaca.markets/support/redistribute-alpaca-api)。这次交付不代表已获得授权，也没有连接交易接口。

## 凭据与依赖

- Windows：用原来保存凭据的同一 Windows 用户启动，自动读取 `%LOCALAPPDATA%\USOptionsDashboard\alpaca-credentials.dpapi`，无需复制该文件。换用户或系统不能直接解密。
- Linux / 容器：由部署环境成对注入 `ALPACA_API_KEY`、`ALPACA_API_SECRET`。Compose 的 environment 已声明可选透传。不要把凭据写进源码、截图、命令参数或日志。
- 两个环境变量只设置一个或格式不合法时明确报配置错误，不静默退回其他账号。都不设置且无可用 DPAPI 时显示待配置，不生成模拟行情。
- 首次连接或更换凭据会执行只读样本验证。配置过程没有下单调用。
- `tzdata==2025.3` 已正式锁定。Windows 和 Linux 都必须安装最新 `requirements.lock`，不能沿用仅含 BTC 依赖的旧环境。

## 本机管理

双击仓库 `start-admin.cmd`。它使用独立的动态回环端口，浏览器自动获得本次启动的随机会话凭证；地址栏随即清除凭证。凭证只保存在该页内存，刷新管理页后需重新启动管理入口，不保存到 localStorage。

管理页可增删自选、增加分类和条目、编辑个人说明。主面板仍只读。两页同时编辑造成版本冲突时返回 409，说明草稿保留，先复制需要保留的内容再重新读取最新版。数据使用原子写入及 `.bak` 备份。

管理与主服务必须使用同一 `OPTIONS_US_DATA_DIR`，默认 `<OPTIONS_RUNTIME_DIR>/us-equities/data`。管理服务不采集行情；主服务每 5 秒读取文档版本，变化后更新，不需要重启。管理端口不可反代到公网。

主面板可以展示该实例的自选和说明，**只读不等于私密**。公网实例应使用经审核的独立资料，不能直接挂载个人运行目录。

## 原项目迁移

原目录保留用于回退。只迁移 `data/watchlist.json` 和存在时的 `data/options-guide.json`；不复制日志、真实行情、虚拟环境、旧服务程序或凭据。当前这台电脑迁入了原有自选列表，原个人说明文件不存在，因此使用内置初稿。

在已激活本项目 Python 环境的 PowerShell 中先预览，再执行：

```powershell
$env:PYTHONPATH = 'src'
python scripts/migrate_us_data.py --source '原项目\data' --destination 'runtime\us-equities\data'
python scripts/migrate_us_data.py --source '原项目\data' --destination 'runtime\us-equities\data' --apply
```

脚本只接受两种已知 JSON，先校验结构，默认不写入；不覆盖任何不同的目标文件。相同文件可重复执行。真实文件位于 `runtime/`，不会进入 Git 或源码 ZIP。

新模块验收后停用旧 8769/8770 监听和启动入口，原目录和配置仍保留。回退时先停止整合版 US 采集，再使用保留的旧程序，避免两套采集器同时请求数据。

## 运维与验证

US 独立锁：`<US data 目录的父目录>/collector.lock`；诊断日志在同级 `logs/`。日志按日轮转、保留 100 天，不记录密钥或行情正文。BTC 的日志和锁路径不变。

`OPTIONS_COLLECTOR_ENABLED=false` 关闭两个市场；`OPTIONS_US_COLLECTOR_ENABLED=false` 只关闭 US。关闭采集不是读取其他进程缓存，页面不会凭空取得旧服务的快照。

`python scripts/verify_us_live.py --url http://127.0.0.1:8782 --symbol GOOG` 观察三轮成功更新，仅请求本地服务，并独立复算所有有效年化和概率。原始真实数据不写入报告。无凭据、网络故障或超时会失败退出，不报告虚假成功。

详细验收见 [US-INTEGRATION-ACCEPTANCE.md](US-INTEGRATION-ACCEPTANCE.md)。Linux 容器、实体手机、真实开盘和提前收市仍需目标环境验证；单元测试中的模拟时间不等于真实市场实测。
