# 开发与验收约定

1. 从 README 和架构图开始。保持 provider（请求/解析）、domain（算法）、runtime（刷新/状态）、api（路由）边界。
2. 计算规则与显示规则分别修改。不得把 null 当成 0，不得用 Mark/成交价悄悄替代 Bid，不得用读接口时间逐秒重算旧收益。
3. 每个模块只有一个采集所有者。修改生命周期、缓存或并发前，先补失败/恢复/多实例测试。
4. 公共入口保持只读；后续编辑功能必须采用网站真正的身份鉴权，不能依据 localhost/Host 判断管理员。
5. 修改文件后运行 Python 和 Node 测试。Windows 用 `scripts/test.ps1`；Linux 命令见下。
6. 页面改动须用真实浏览器检查。测试夹具通过不能代替 HTML/脚本组合、样式、窄屏和刷新恢复的实际验证。
7. 变更接口、配置或模块边界时同步 docs。依赖升级更新 lock，并记录 Python/框架版本与复测结果。
8. 日志、快照、密钥、真实 `.env`、虚拟环境不提交。`/runtime/` 的忽略规则必须保持根目录限定，不能误忽略 `src/options_panel/runtime/`。

```sh
export PYTHONPATH="$PWD/src"
python -m pip install -r requirements-dev.lock
python -m compileall -q src tests scripts
python -m unittest discover -s tests -v
node tests/test_ui.js
node tests/test_guide.js
node tests/test_bootstrap.js
```

维护说明时编辑 `content/options-guide.json` 的 section/topic 正文，保持唯一 ID。内容审核通过后更新 `revision`（字符串）和 `updated_at`（UTC ISO），运行测试后发布。浏览器没有写入接口。
