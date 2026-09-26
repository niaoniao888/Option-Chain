# 如何交给朋友 / 放到 GitHub

GitHub 仓库是保存项目文件和变更历史的地方；**上传源码不等于网站已经运行**。此项目需要 Python 后端，不能只用 GitHub Pages 托管静态 HTML 就获得实时行情。[GitHub 仓库说明](https://docs.github.com/en/get-started/start-your-journey/creating-a-repository-for-your-project-on-github)

## 当前仓库

仓库地址：https://github.com/niaoniao888/Option-Chain 。原名称 `options-panel` 已重定向到同一个仓库。源码在根目录按文件夹展开；原始 ZIP 和 SHA-256 校验文件保留在根目录。请在现有仓库克隆后创建工作分支，不要重新初始化或强制覆盖远端历史。

```sh
git clone https://github.com/niaoniao888/Option-Chain.git
cd Option-Chain
git switch -c feature/your-change
```

私有仓库需要所有者授予协作者访问权限。上传源码不代表已邀请协作者或已部署网站。

## 最省事的交接方式

运行项目根目录中的打包脚本：

```powershell
.\.venv\Scripts\python.exe scripts\package_release.py
```

把 `dist/` 中的 ZIP 和对应 `.sha256` 文件交给朋友。对方解压后先读 README，再按部署说明接入网站。ZIP 包含源码、前端、内容、测试、文档、部署配置和 CI；不含你的虚拟环境、行情日志、缓存、真实 `.env`、Git 历史或个人快捷方式。

`FILE-MANIFEST.json` 记录包内每个源文件的 SHA-256。ZIP 同名 SHA-256 文件用于核对传输是否改变。打包不执行上传，不会自动创建 GitHub 仓库。

## 自己在 GitHub 创建仓库

1. 在 GitHub 注册/登录自己的账户，选择 New repository。
2. 名称可用 `options-panel`。建议先选 **Private**，便于只向合作团队交接。
3. 如果按下面命令上传，创建空仓库，不勾选自动 README、`.gitignore` 或许可证，因为项目已提供前两项；许可证由你和团队决定，本次没有擅自赋予公开开源许可。
4. 创建后复制仓库的 HTTPS 地址。
5. 可把经过打包过滤的源码交给团队，由他们上传；也可自行执行下面命令。不要把整个带 `.venv` 的工作目录直接拖进网页。

## Git 命令方式（首次、在本项目根目录执行）

需要先安装 Git；姓名、邮箱和仓库地址替换为自己的实际值。登录授权通过 GitHub/Git Credential Manager 自己完成，无需把密码或令牌发给别人。

```powershell
git init -b main
git config user.name "你的提交显示名"
git config user.email "你的GitHub提交邮箱"
git add -- README.md CONTRIBUTING.md CHANGELOG.md pyproject.toml requirements.txt requirements.lock requirements-dev.lock start-panel.cmd Dockerfile compose.yaml .env.example .gitignore .dockerignore .github src web content tests scripts docs deploy
git status --short
git diff --cached --stat
git commit -m "Initial options panel handoff"
git remote add origin https://github.com/你的账号/options-panel.git
git push -u origin main
```

执行 commit 前，确认暂存区没有真实 `.env`、`.venv`、根目录 `/runtime/`、`/dist/`、日志或账号信息；`src/options_panel/runtime/` 是后台运行逻辑源码，必须保留。仓库已经存在时，不要重复初始化/覆盖历史；让团队合并到其仓库。后续按改动文件精确暂存和提交。

上传后，在仓库 Settings → Collaborators 中邀请朋友的 GitHub 账号，并让对方确认能 clone、运行测试、启动服务。邀请协作者由仓库所有者操作；本次整理不会自动邀请任何人。

## 交接给团队的话

> 项目后端是 Python/FastAPI/Uvicorn，前端是原生 HTML/CSS/JS。请先看 README、docs/ARCHITECTURE.md 和 docs/OPERATIONS.md。公开服务只读，当前一个 worker 共用行情缓存；可挂在网站 /options/ 子路径。BTC 与 Alpaca 美股均已实现；配置见 docs/US-EQUITIES.md，扩展边界见 docs/EXTENDING.md。实际测试和未验证项见 docs/ACCEPTANCE.md。
