# 期权面板 · 比特币模块

此仓库保存 **2.0.0 完整源码交接包**。源码、前端、测试、部署配置和中文文档全部在压缩包中；当前仓库采用压缩包交付，并非展开的源码工作树。

## 下载与使用

1. 点击 [options-panel-2.0.0.zip](options-panel-2.0.0.zip)，再点击下载原始文件按钮。
2. 解压后打开 `options-panel/README.md`。
3. Windows 安装 Python 3.13 后，双击项目中的 `start-panel.cmd`；首次启动会安装依赖。
4. 本机入口为 `http://127.0.0.1:8780/`。公网部署请由网站团队按包内文档配置。

## 团队接手入口

- `docs/ARCHITECTURE.md`：结构、职责和数据流。
- `docs/API.md`：接口契约。
- `docs/CALCULATIONS.md`：年化、单期收益和概率口径。
- `docs/OPERATIONS.md`：网站集成、配置与运维。
- `docs/EXTENDING.md`：增加美股等并列模块。
- `docs/MIGRATION.md`：原项目与交接项目关系。
- `docs/ACCEPTANCE.md`：实际验收记录与未验证项目。

后端为 Python + FastAPI + Uvicorn，前端为原生 HTML / CSS / JavaScript。包含 PC 和手机版、单后台采集与共享快照、Docker / Nginx 部署示例、测试和 GitHub CI 配置。CI 配置目前在压缩包内，需展开源码后才会在仓库运行。

本机已通过 64 项 Python 测试和 3 组 Node 测试，并核验真实币安行情；Docker、Linux 及公开域名部署尚未实测，详见包内验收文档。

## 完整性校验

压缩包 SHA-256：

```text
3c64ab5b34c779e7a04c02978d52133a4af8862feb57100ffbe2deba2b0b7ca4
```

另附 [校验文件](options-panel-2.0.0.zip.sha256)。包内 `FILE-MANIFEST.json` 记录文件清单及校验值。

此包不包含本地运行日志、虚拟环境、行情缓存或真实密钥。只提供行情看板，不接账户和交易。
