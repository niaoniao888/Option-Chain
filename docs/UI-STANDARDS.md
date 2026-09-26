# 统一界面规范：BTC ui10 基准

四个 BTC/美股桌面与手机入口共用 `web/app/index.html` 和 `web/app/styles.css`。市场特色在 `web/app/markets/` adapter 中表达；不要复制页面或用隐藏溢出掩盖布局问题。

主题变量必须保持已验收颜色：

| 变量 | 浅色 | 深色 |
| --- | --- | --- |
| bg | #f5f7fb | #0e1624 |
| card | #ffffff | #172235 |
| ink | #17233c | #e7edf8 |
| muted | #66728a | #aab6c9 |
| line | #dfe5ef | #34435c |
| blue | #2864dc | #82adff |
| soft | #edf3ff | #243a60 |
| green | #087c61 | #74dfbd |
| red | #c54141 | #ff9ba2 |

| 项目 | PC | 手机（<=700px） |
| --- | --- | --- |
| 标题 | 22px | 响应式保留价格标题 |
| 主题按钮 | 34×28px | 34×30px |
| 模块按钮 | 20px、圆角9px | 14px、高32px、圆角8px |
| Call/Put | 高44px、18px、组宽240px | 高38px、组宽136px |
| 期限按钮 | 高44px、16px、400 | 高38px、自适应 |
| panel | 圆角14px | 圆角11px |
| 期权链 | 1200px，允许横向查看 | sticky 行权价，按 BTC 紧凑字号 |
| 价格表 | 725px，150/175/130/120/150 | 容器内固定布局，11–12px |
| 排行 | 10条/页，页码34×34 | 全列保留，11–12px |

上涨红、下跌绿；空值不当作 0。PC “单期收益率”，手机“单期收益”。美股到期时间按 expires_at_utc 转中国时间；同一 expiration_date 对应多个 UTC 时显示“—”。动态文本不得经 innerHTML 插入。

验收覆盖 BTC/US × chain/price/ranking × 深浅主题，手机 320/390/430，桌面 1280/1920 及 150% 缩放。保存 Playwright HTML 报告与每个组合截图；另验证排序、分页、跨股票恢复、菜单键盘焦点、复制保护、hidden/timeout/乱序恢复和同代 DOM 稳定。实体手机与跨操作系统字体像素差异需在交付记录中如实说明。
