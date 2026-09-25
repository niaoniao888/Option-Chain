# 原项目到交接版的映射

这是一份独立源码交付，不会移动或删除原项目。来源基线的相对路径、大小、SHA-256 见 [source-manifest.json](provenance/source-manifest.json)。不携带旧日志、浏览器截图、快捷方式和运行缓存。

| 原文件 | 交接位置 / 处理 |
| --- | --- |
| `server.py` 计算函数 | `domain/calculations.py`，10 个函数迁移时 AST 核对一致 |
| `server.py` 请求与解析 | `providers/binance.py` |
| `server.py` 状态与采集 | `runtime/snapshot.py`、`runtime/refresher.py` |
| `server.py` HTTP / 启动 | FastAPI `api.py`、Uvicorn `cli.py`，不再用 ThreadingHTTPServer |
| `mobile_server.py` | 退役；手机版与桌面版由同一个新服务提供，不再代理旧 PC 端口 |
| `guide_store.py` | 新 `content/guide_store.py` 只读校验；原匿名本机编辑接口不进入公共版 |
| `static/index.html`, `app.js`, `style.css` | `web/desktop/` |
| `static/mobile.html`, `mobile.js`, `mobile.css` | `web/mobile/`，入口文件统一叫 `index.html` |
| `static/guide.js`, `guide.css` | `web/shared/` |
| `data/options-guide.json` | `content/options-guide.json`，保留已编辑正文 |
| 本机 `.lnk` 与含个人 Python 路径的入口 | 不复制；新的相对路径脚本与 `start-panel.cmd` |
| 旧 README / 长期验收流水 | 本文档体系重新梳理；原文仍在原项目，交接包不塞入重复历史文件 |

## 测试迁移

原项目基线：73 个 Python 用例与 2 套 Node 测试通过。数学、解析、冻结代次、到期、OI、概率、网络重试和恢复等业务回归迁移到新包。

旧 ThreadingHTTPServer、手机独立网关、匿名本机写说明等专属 HTTP 测试退役，改为 FastAPI 路由、只读写拒绝、基路径、进程锁、日志和资源边界测试。计数变化不是宣称所有原 HTTP 行为仍存在。新测试数量与实际结果见验收记录。

`tests/legacy_support.py` 只是旧回归用例的导入桥，避免改变原断言；生产代码不导入它。新测试直接导入对应模块。整页脚本声明冲突另有 `test_bootstrap.js` 检查。

## 明确的行为变化

- 新入口新增“期权面板 → 比特币”层级和版本化 API。
- 新服务默认 8780，不占旧 8766/8768。
- 公开 PC/手机均只读；维护说明请编辑仓库内容。原本机 PC 编辑仍留在旧项目。
- 子路径、同源嵌入、Host 白名单、GZip、短响应缓存、部署文件为交接版新增。
- 不改变收益、概率、Bid 异常提示、红涨绿跌、筛选/选择持久化的业务口径。

## 2.1.0 美股整合

旧美股根目录业务 Python 文件迁到 `src/options_panel/us_equities/`，改为包内导入；原 static 迁到 `web/us-equities/`。旧 PC writer / mobile gateway 不迁入，以 FastAPI 只读 API 与独立 admin 替代。主项目不依赖旧路径。仅私有运行数据按 [美股迁移步骤](US-EQUITIES.md) 复制，旧文件保留。
