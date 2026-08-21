# cs-skin-market · 轻量云(Lighthouse)部署手册

> 状态：**部署准备完成，尚未实际部署**（代码仍在迭代，待用户 push 最新代码后执行）。

## 目标实例

| 项 | 值 |
|---|---|
| 实例 ID | lhins-hbwk0l3e |
| 地域/可用区 | 上海 ap-shanghai-5 |
| 配置 | 2 核 / 2 GB，50 GB SSD |
| 镜像 | Ubuntu Server 24.04 LTS |
| 公网 IP | 118.25.48.58 |
| 带宽 | 4 Mbps |
| 到期 | 2026-09-20（首月免费奖励）|

## 已完成的准备（本次）

1. **防火墙 8000 端口已对 0.0.0.0/0 开放**（TCP，ACCEPT）——任何人都可访问 Web UI（按用户要求）。
2. **服务器环境探测通过**：Ubuntu 24.04 / Python 3.12.3 / git 2.43 / GitHub 连通 200 / TAT 代理就绪 / 1.9 Gi swap 兜底。
3. 写好一键部署脚本 `deploy_cs_skin_market.sh`（本目录）。

## 真正部署时执行（待用户喊"部署"）

通过 Lighthouse 远程命令(TAT) 在实例上以 root 跑部署脚本：

```bash
bash /path/to/deploy_cs_skin_market.sh
# 或在线拉取：
bash <(curl -fsSL https://raw.githubusercontent.com/DarcyYang2020/cs-skin-market/main/deploy_cs_skin_market.sh)
```

脚本会依次：装系统依赖 → git clone 仓库 → 建 venv 装 Python 依赖 → `playwright install chromium`（见下"采集方式"说明）→ 写 `run_prod.py`（绑定 0.0.0.0:8000，不改仓库代码）→ 注册 systemd 服务 → 配置每日采集 cron。

## 采集方式（2026-08-21 核实，已修正旧认知）

**每日 18:00 主任务（K线全量刷新）现在走 csQAQ 直连 API，不是 Playwright。** 具体：

- `collect_bind_ip()` / `fetch_market_index()` / `_fetch_macro()`：全部 urllib 直连 API（带 ApiToken）。
- `collect_kline_all()`（最重的一步）：先 `fetch_kline_90d_api`（urllib + ApiToken 直连 `/info/chart`），**仅在 API 返回空/401/429 时**才回退 `fetch_kline_90d`（Playwright 浏览器）。
- 故普通日子的 18:00 任务**完全不碰浏览器**，负载很轻。

**Playwright 浏览器仍在以下场景使用，所以 Chromium 必须装：**

1. K线 API 兜底（API 偶发失败时）。
2. **每周一**的额外任务：全市场快照 / 大户集中度 / 求购观察（snapshot、monitor、bids）。
3. **Web UI** 的「搜索并分析单品」（`search_good_id` + `fetch_item_detail`，纯浏览器，无法绕过）。

> 若只跑每日 API 采集、且不用 Web UI 搜索，可部署时 `SKIP_CHROMIUM=1` 跳过 Chromium 安装（省内存/磁盘），但周一任务与 Web UI 搜索将不可用。

## 部署后验证

```bash
curl -sI http://118.25.48.58:8000/          # 应返回 200（大盘豁免登录，可看）
curl -sI http://118.25.48.58:8000/watchlist # 未登录应 302 → /login（受保护页门禁生效）
# 登录冒烟（需先部署时注入 CS_MARKET_PASSWORD）：
curl -s -i -c /tmp/cs.cookie -X POST http://118.25.48.58:8000/login \
     -d "password=你的密码" | head -5        # 正确密码应 302 + Set-Cookie httponly
curl -s -b /tmp/cs.cookie http://118.25.48.58:8000/watchlist  # 带 cookie 应 200
systemctl status cs-skin-market             # active(running)
journalctl -u cs-skin-market -n 50          # 看启动日志
```

## 关键注意点

- **公网暴露 + 鉴权（AUTH-1 已验收，2026-08-21 DA 关闭）**：防火墙 8000 仍对 0.0.0.0/0 全开（用户确认"任何人可访问"），但 Web UI **已加密码门禁**——受保护页面/API 需登录（POST /login 正确密码→302+httponly cookie；错误密码→401）。大盘 `/` 与少数只读 API 豁免（AUTH_EXEMPT_PATHS）。**部署必须注入 `CS_MARKET_PASSWORD`**（否则 `/login` 500）；`CS_MARKET_SESSION_SECRET` 建议一并注入（否则重启后会话失效）。部署脚本已加 [3b] 步：从环境变量读 `CS_MARKET_PASSWORD` 写入 `/opt/cs-skin-market/.env`（权限 600）。用法：`CS_MARKET_PASSWORD='你的密码' bash deploy_cs_skin_market.sh`。
- **0.0.0.0 绑定**：仓库 `run_server.py` 绑定 `127.0.0.1`，公网不可达；部署改用 `run_prod.py` 绑定 `0.0.0.0`，不动仓库代码。
- **内存**：2 GB 偏紧。注意——**每日 18:00 的 K线采集主体是直连 API，很轻**；Chromium 只在周一任务、API 兜底、Web UI 搜索分析时才被拉起（headless Chromium 约占 300–500MB）。已靠 1.9 Gi swap 兜底；若周一任务或 Web UI 搜索频繁 OOM，升级 2C4G 或设 `SKIP_CHROMIUM=1` 仅跑 API 采集。
- **cron 时区**：Lighthouse 默认多为 UTC。脚本默认每日 18:00（UTC）；若需"北京时间 18:00"应在 UTC 服务器填 10:00，部署时确认。
- **代码同步**：部署前请务必 `git push` 最新代码到 `https://github.com/DarcyYang2020/cs-skin-market.git`，脚本会 `git clone/pull` 该仓库。
- **数据**：SQLite（`data/market.db`）在仓库目录内，全新 clone 后首次运行由程序建表，每日采集填充；重装会清空，需另行备份。
