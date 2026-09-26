# Linux Docker 交接：从这里开始

本方案面向 Ubuntu 24.04 x86_64、Docker Engine 与 Docker Compose v2。服务只绑定主机 `127.0.0.1:8780`，由 Nginx 提供 HTTPS。容器使用 UID 10001、只读根文件系统、单个 Uvicorn worker 和命名数据卷；不要并行启动第二个采集实例。

## 首次启动

```sh
VERSION=2.1.0
COMMIT=abcdef12  # 替换为 Release 标签末尾的 8 位 commit
BUNDLE="options-panel-${VERSION}-g${COMMIT}"
grep -E '(-linux\.tar\.gz|-FILE-MANIFEST\.json)$' "${BUNDLE}-SHA256SUMS.txt" | sha256sum -c -
tar -xzf "${BUNDLE}-linux.tar.gz"
cd options-panel
cp .env.example .env
# 编辑 .env：填写实际域名；若需要美股行情，再安全填写成对的 Alpaca 变量。
chmod 600 .env
./scripts/options-panel.sh check
./scripts/options-panel.sh start
./scripts/options-panel.sh status
```

默认地址为 `http://127.0.0.1:8780/options/`。两个 Alpaca 变量同时留空表示未配置，美股显示待配置，BTC 和页面仍可启动。不得把 `.env` 提交 Git 或加入发布包。

控制入口：`check` 检查 Docker 与 Compose 配置但不打印配置内容；`start` 构建并启动；`status` 在容器内检查 healthz；`logs [行数]` 查看有限日志；`stop` 最多等待 300 秒优雅停止。停止不会删除命名卷。

## 个人数据与离线管理

管理 CLI 不启动行情采集器或 HTTP 服务。先用 `list` 取得 revision，每次写入都必须带当前 revision：

```sh
REV=$(docker compose exec -T options-panel python -m options_panel.manage watchlist revision)
docker compose exec options-panel python -m options_panel.manage watchlist add AAPL --revision "$REV"
REV=$(docker compose exec -T options-panel python -m options_panel.manage watchlist revision)
docker compose exec options-panel python -m options_panel.manage watchlist remove AAPL --revision "$REV"

REV=$(docker compose exec -T options-panel python -m options_panel.manage guide revision)
docker compose exec options-panel python -m options_panel.manage guide export /tmp/guide.json
docker compose cp options-panel:/tmp/guide.json ./guide-edit.json
# 编辑 guide-edit.json 的 sections，保留其中的 revision 字段。
docker compose cp ./guide-edit.json options-panel:/tmp/guide-import.json
docker compose exec options-panel python -m options_panel.manage guide import /tmp/guide-import.json --revision "$REV"
```

导出到卷外时使用 `docker compose cp`，不要把导出文件放进 Git。备份/恢复只处理 `watchlist.json`、`options-guide.json` 及其原子备份，不含日志、锁、行情缓存或凭据。两者都要求主服务已经停止；恢复前自动生成安全备份，并保留命名卷：

```sh
./scripts/options-panel.sh stop
./scripts/options-panel.sh backup
./scripts/options-panel.sh restore /absolute/path/backups/options-panel-data-YYYYmmddTHHMMSSZ.tar.gz
./scripts/options-panel.sh start
```

恢复会先拒绝路径穿越、链接、重复成员、超限文件和无效 JSON，再修改现有数据。

## Nginx、更新与回滚

子路径部署使用 [nginx-location.conf](../deploy/nginx-location.conf)，保留 `/options` 前缀；根路径部署使用 [nginx-root.conf](../deploy/nginx-root.conf)，并把 `.env` 中 `OPTIONS_BASE_PATH` 明确留空。不要同时配置 Uvicorn `root_path` 或剥除一次前缀。

生产使用通过 CI 的 `linux-<version>-<shortsha>` Release 资产。`compose.yaml` 固定 project name 为 `options-panel`，`COMPOSE_PROJECT_NAME` 可在隔离测试中覆盖；生产不要改名，否则换源码目录后会得到另一套命名卷：

```sh
VERSION=2.1.0
COMMIT=abcdef12  # 替换为 Release 标签末尾的 8 位 commit
BUNDLE="options-panel-${VERSION}-g${COMMIT}"
grep -E '(-linux\.tar\.gz|-FILE-MANIFEST\.json)$' "${BUNDLE}-SHA256SUMS.txt" | sha256sum -c -
export COMPOSE_PROJECT_NAME=options-panel
OLD_IMAGE=$(docker compose images -q options-panel)
docker image tag "$OLD_IMAGE" options-panel:rollback-$(date -u +%Y%m%dT%H%M%SZ)
./scripts/options-panel.sh stop
./scripts/options-panel.sh backup
# 解压新包、复制 chmod 600 的 .env，并把 OPTIONS_IMAGE 改为 "options-panel:${VERSION}-g${COMMIT}"
./scripts/options-panel.sh start
```

如升级验收失败，把 `.env` 的 `OPTIONS_IMAGE` 改成上一步的 `options-panel:rollback-...`，在对应源码目录执行以下命令，禁止重新 build 覆盖回滚镜像：

```sh
export COMPOSE_PROJECT_NAME=options-panel
docker compose stop --timeout 300 options-panel
docker compose up -d --no-build --force-recreate options-panel
./scripts/options-panel.sh status
```

不要执行 `docker compose down -v`。基础镜像当前仍是版本标签，首次验收后应记录实际 digest，后续显式审核 digest 变化。

详细配置见 [运行维护](OPERATIONS.md)，架构边界见 [架构](ARCHITECTURE.md)，开发验证见 [贡献约定](../CONTRIBUTING.md)。
