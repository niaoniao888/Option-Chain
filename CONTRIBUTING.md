# 开发与验收约定

1. 从 README、架构和界面规范开始。保持 provider、domain、runtime、routes 与前端 adapter/component 边界。
2. 不得把 null 当 0，不得用 Mark/成交价代替 Bid，不得在浏览器重算冻结的收益和概率。
3. 每个市场只有一个采集所有者。改生命周期、缓存、租约或队列前先补失败、恢复和重复启动测试。
4. 公共入口只读；本机管理页继续使用会话授权，不能以 localhost 或隐藏按钮代替鉴权。
5. 新 provider 通过 ProviderRegistry 注入同一 MarketRuntime；新市场通过 MarketRegistration 声明 descriptor、路由和静态页面。
6. 通用前端只操作 adapter 协议；市场特有日期、资格、列、精度和展示由 adapter 提供。
7. 页面改动须验证 BTC/US × 桌面/手机 × 三视图 × 深浅主题，并覆盖 320/390/430/1280/1920 和 150% 缩放。
8. 变更接口、配置、注册协议或目录时同步 docs；依赖变更同步 package lock 或 Python lock。
9. 日志、快照、密钥、真实 .env、虚拟环境和 Playwright 运行报告不提交。

Windows PowerShell：

```powershell
# 首次准备（生产运行不需要 Node 或浏览器测试依赖）
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup.ps1 -Development
npm ci
npx playwright install chromium
$env:PATH = "$PWD\.venv\Scripts;" + $env:PATH
$env:PYTHONPATH = "src"
$env:OPTIONS_COLLECTOR_ENABLED = "false"
& .\.venv\Scripts\python.exe -m compileall -q src tests scripts
& .\.venv\Scripts\python.exe -m unittest discover -s tests -v
node tests/test_ui.js
node tests/test_bootstrap.js
npm run format:check
npm run test:e2e
& .\.venv\Scripts\python.exe scripts\package_release.py
```

说明 JSON 和管理存储继续由后端测试覆盖；主看板已取消说明 UI 和旧 `web/shared` 渲染资源。

Linux 容器运行验收在 Ubuntu 24.04 x86_64 CI 中从刚生成并解压的 tar.gz 执行 `scripts/ci_container_runtime.sh`。它覆盖根路径/子路径、四个页面、静态资源与 API、只读根文件系统、UID 10001、卷持久化、优雅停止、备份恢复、单实例和空凭据。发布 job 只在 Python、Node、浏览器和容器任务全部通过后接受 `linux-<version>-<shortsha>` 标签，并上传同一个已测试的包。
