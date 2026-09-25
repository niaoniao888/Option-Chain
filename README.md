# 期权面板 · 比特币模块

这是从原本地 BTC 看板整理出的独立交接项目（2.0.0）。后端 **Python + FastAPI + Uvicorn**，前端 **原生 HTML / CSS / JavaScript**。一个后台采集 Binance Options 公开行情，桌面和手机共用快照。网站可将整个项目挂在 `/options/`，并在模块入口中逐步增加美股等市场。

本目录是独立项目；原来的本地看板、网址和运行进程不依赖它。此交接版没有连接交易账户，也没有交易接口。所有网页接口只读；说明内容由维护人员编辑 `content/options-guide.json`。

## GitHub 源码与版本包

本仓库直接提供可阅读和克隆的完整源码。根目录保留 [2.0.0 原始交接压缩包](options-panel-2.0.0.zip) 和 [SHA-256 校验文件](options-panel-2.0.0.zip.sha256)，便于独立下载；该 ZIP 为交接时的固定快照，不会随仓库后续修改自动更新。日常开发以仓库当前分支为准。

## 先看哪里

| 读者 / 目的 | 文件 |
| --- | --- |
| 使用者：打开看板、交给朋友 | 本 README、[GitHub 与压缩包交接](docs/GITHUB.md) |
| 接手工程师：理解设计及迁移范围 | [架构](docs/ARCHITECTURE.md)、[技术选型](docs/STACK.md)、[迁移映射](docs/MIGRATION.md) |
| 前端工程师：接入现有网站 | [接口契约](docs/API.md)、[集成与部署](docs/OPERATIONS.md) |
| 金融功能维护：计算含义 | [计算口径](docs/CALCULATIONS.md) |
| 增加美股等模块 | [模块扩展](docs/EXTENDING.md) |
| 测试和上线负责人 | [验收记录与限制](docs/ACCEPTANCE.md)、[贡献约定](CONTRIBUTING.md) |

## Windows 本机启动

建议安装 Python 3.13。**双击根目录 `start-panel.cmd`**。首次会在本目录创建 `.venv` 并从 PyPI 安装锁定的依赖，需要联网；以后直接使用该环境。窗口保持运行即可，不需要打开 GPT。

- 模块入口：`http://127.0.0.1:8780/`
- 桌面版：`http://127.0.0.1:8780/bitcoin/desktop/`
- 手机版预览：`http://127.0.0.1:8780/bitcoin/mobile/`

这些是本机预览地址。手机实体设备不能使用电脑的 `127.0.0.1`；局域网预览见部署说明。端口 8780 已运行时，直接访问，不要重复启动。关闭启动窗口或 Ctrl+C 可停止这一交接版进程。

也可以在项目目录的 **PowerShell** 中执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup.ps1 -Development
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start.ps1 --open
```

## Linux / 团队开发

以下命令在项目根目录的 **Linux shell** 中执行。源码、`web/`、`content/` 必须一起保留；当前交付形式是源码项目，不是单独上传一个 Python wheel。

```sh
python3.13 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-dev.lock
export PYTHONPATH="$PWD/src"
python -m options_panel --host 127.0.0.1 --port 8780
```

## 文件与文件夹

```text
比特币面板/
├── README.md                 从这里开始
├── CONTRIBUTING.md           修改与测试约定
├── CHANGELOG.md              交接版变更
├── pyproject.toml            Python 包与依赖范围
├── requirements.txt          允许的直接运行依赖范围
├── requirements.lock         实际验收的完整运行依赖
├── requirements-dev.lock     测试依赖
├── start-panel.cmd           Windows 双击启动
├── src/options_panel/        后端；各文件职责见架构文档
├── web/                      浏览器界面
│   ├── hub/                  一级“期权面板”模块入口
│   ├── desktop/              比特币桌面版
│   ├── mobile/               比特币手机版
│   └── shared/               共用说明显示
├── content/                  经维护人员审核的说明内容
├── tests/                    不访问 Binance 的回归测试
├── scripts/                  安装、启动、测试、验证、打包
├── docs/                     中文交接文档、依据和验收证据
├── deploy/                   现有网站 Nginx 接入示例
├── Dockerfile                非 root 容器
├── compose.yaml              单实例、自动重启、日志上限
├── .env.example              部署配置示例，无账号信息
├── .github/workflows/ci.yml   Windows / Linux 测试与容器构建
├── .venv/                    本机运行时生成，不提交、不打包
├── runtime/                  本机日志与验证输出，不提交、不打包
└── dist/                     打包输出，不提交、不嵌套打包
```

## 验证与交接

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test.ps1
.\.venv\Scripts\python.exe scripts\verify_live.py
.\.venv\Scripts\python.exe scripts\package_release.py
```

`verify_live.py` 需要服务已经启动，观察三个成功行情代次；只请求本机服务，不会自行调用 Binance。打包脚本生成可分享 ZIP、文件哈希清单和 ZIP 的 SHA-256，排除虚拟环境、日志、缓存、真实部署配置。

上面的无参数验证命令对应本机默认根路径。**若按 Compose 默认部署在 `/options`，验证时必须包含前缀**：

```powershell
.\.venv\Scripts\python.exe scripts\verify_live.py --url http://127.0.0.1:8780/options
```

**公开部署使用一个 worker、一个实例。** 由网站的 HTTPS 反向代理提供公网入口。不要直接开启多个 Uvicorn worker；先读 [部署说明](docs/OPERATIONS.md)。本项目已提供部署文件，实际域名、Linux 容器部署及站点容量仍需接手团队验收。
