# 期权面板项目规则

- 开始前阅读 README.md、CONTRIBUTING.md、docs/ARCHITECTURE.md 与 docs/UI-STANDARDS.md。
- 四个 BTC/美股桌面与手机入口共用 `web/app/index.html`、`web/app/styles.css` 和 ESM 组件；不得再复制整套市场页面。
- `web/app/core/` 只放状态、轮询、模型和通用格式；`components/` 不判断市场 ID；市场字段、资格、日期、列和金融展示差异放在 `markets/` 适配器。
- BTC 是通用视觉与交互基准。改共享样式须核对 BTC/US、桌面/手机、深/浅主题和 320/390/430/1280/1920 宽度。
- 前端不得重算后台年化、单期收益或行权概率；本地投影只推进倒计时、到期、校对状态和资格边界。
- 每个市场只有一个采集所有者。生命周期由 RuntimeLifecycle 和 ProcessLock 监督；BTC 与 US 的刷新编排仍可保留各自策略。
- 新市场通过后端 MarketRegistration/ProviderRegistry 与前端 registerMarketAdapter 注册。新增适配器不得要求修改 Dashboard 的市场分支。
- 动态市场标签、股票、期限和菜单内容均视为不可信文本，使用 DOM textContent 或统一转义；禁止拼接脚本 URL。
- 页面变更须运行 Node 行为测试及 Playwright；自动测试通过后仍检查真实浏览器 computed style、溢出和交互。
- 不修改个人凭据、运行数据、生产服务或历史压缩包。日志不得记录异常正文、URL 查询凭据或密钥。
