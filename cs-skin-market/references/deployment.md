# 个人部署方案（解决「关机即停」）

> 2026-08-10 起草。当前 Web 服务（run_server.py，127.0.0.1:8000）与 4 个计划任务都跑在开发机上，关机即停。目标：把系统搬到一台 7x24 常开机器，全自动采集/推送/监控。

## 1. 两条路径对比

| | A. 家里常开设备（推荐，零月费） | B. 云服务器（稳定，有月费） |
|---|---|---|
| 载体 | 旧电脑/笔记本/迷你主机/NAS 长期插电 | 腾讯云/阿里云轻量 |
| 迁移成本 | 低（Windows 则与本机 100% 一致） | 低（Windows Server）~ 中（Linux 需适配） |
| 月费 | 0（电费可忽略） | Windows Server 约 150-250 元；Linux 约 50-80 元 |
| 网络/IP | 家庭宽带 IP 会变，csQAQ 401 自动 rebind 重试（已有退避） | 固定公网 IP，绑定一次最稳 |
| 断电风险 | 有（可选配 UPS） | 无（机房） |

推荐顺序：A（家里可常开 Windows 机器）> B-Windows Server > B-Linux。
关键约束：csQAQ 有 IP 绑定（401 自动 rebind），Playwright + 悠悠锚价要求出口 IP 稳定且能访问国内站点。
## 2. 共用迁移清单（A/B 都适用）

1. 全量拷贝 cs-skin-market/ 目录（含 data/ 约 260MB、.env 凭据、market.db）；
2. 新机器装 Python 3.11（与现机器同版本）；
3. pip install -r requirements.txt（fastapi/uvicorn/jinja2/playwright，已固化）；
4. python -m playwright install chromium（采集必需，首次下载约 150MB）；
5. 注册计划任务：cd cs-skin-market && powershell -ExecutionPolicy Bypass -File install_tasks.ps1
   - 18:00 CS_Skin_DailyCollect（全量采集+健康检查+每日备份+数据质量复核周日+J-2 刷新+信号跟踪回填+监控事件生成）
   - 12:00 CS_Skin_NoonMonitor（午间监控+钉钉推送）
   - 21:30 CS_Skin_NightPush（晚间监控+钉钉推送）
   - 22:00 CS_Health_Alert（健康 FAIL 钉钉告警）
6. Web 服务常驻（见下节）；
7. 首次验证：python run_daily_collect.py 全量跑通（观察 IP 绑定、kline 失败台账为空）；
8. 钉钉验证：python notify_alert.py --title "CS 监控 部署验证" --text "监控部署完成"（须含关键词「监控」，加签 secret 已在 .env）。

## 3. Web 服务常驻

- Windows 推荐 NSSM：nssm install CS_Market "python 绝对路径" "run_server.py 绝对路径"，nssm set CS_Market AppDirectory cs-skin-market 路径，nssm start CS_Market（开机自启+崩溃重启，日志可重定向到 data/server.log）；
- Windows 备选：计划任务「登录时启动」或启动文件夹（需用户登录）；
- Linux：systemd unit（ExecStart=python run_server.py，Restart=always）。
## 4. 远程访问（手机/公司电脑查看）

- 推荐 Tailscale（免费组网）：常开机器与手机/笔记本都装 Tailscale，任意设备浏览器访问 http://<常开机器TailscaleIP>:8000；服务保持监听 127.0.0.1，由 Tailscale 网卡路由，无需改防火墙；
- 备选（云服务器）：uvicorn host=0.0.0.0 + 云防火墙只放行 Tailscale 网段/固定 IP，不建议裸公网（无认证）；
- 手机日常：直接看钉钉日报（12:00/21:30），网页仅在需要扫描/分析时打开。

## 5. 网络/IP 绑定注意事项

- 部署机器不要挂 VPN/代理（频繁触发 csQAQ 401 rebind，采集失败率上升）；
- 家庭宽带重拨换 IP：首次 401 自动 rebind 重试（退避 1.5s + 失败台账），通常自动恢复；连续失败看 data/kline_fail_count 与健康检查钉钉告警；
- 云服务器固定公网 IP，绑定一次长期有效。

## 6. 数据备份（market.db 是核心资产）

- 每日：run_daily_collect.py 收尾自动 backup_db.backup(keep=14) -> data/backup/（14 份滚动）；
- 每周冷备（可选）：把 data/market.db + data/*.json 产物拷到外接盘/网盘，保留 4 周；
- 数据库损坏恢复：停服务 -> 从 data/backup/ 最新备份还原 -> 重启。

## 7. 安全

- .env 含 csQAQ token 与钉钉 secret，已被 gitignore；NTFS 可 icacls 限当前用户读；
- 服务监听 127.0.0.1（默认已正确），外网一律走 Tailscale/白名单，不做裸端口转发；
- 钉钉机器人已加签（secret 在 .env）+ 关键词「监控」规则。

## 8. 升级流程（日常迭代）

1. git pull（或开发机改完推送后 pull）；
2. python tests/test_smoke.py 全量通过（98 项）；
3. 重启 Web 服务（nssm restart CS_Market 或手动）；
4. 验证 http://127.0.0.1:8000/ HTTP 200；若改采集/回放产物，按「回放同源」纪律重跑 sync 脚本。

## 9. 上线验证清单

- [ ] python run_daily_collect.py 全量成功（日志无 FAIL，kline 失败台账为空）
- [ ] http://127.0.0.1:8000/ HTTP 200
- [ ] 钉钉收到 12:00 午间推送（含「监控」关键词）
- [ ] 钉钉收到 21:30 晚间推送
- [ ] data/backup/ 出现当日备份
- [ ] 手机通过 Tailscale 能打开 Web 页面
- [ ] 重启机器后：服务自动拉起（NSSM），次日 18:00 采集自动恢复

## 10. 现状缺口（已补/待办）

- 已补：requirements.txt 固化依赖（2026-08-10）；
- 已有：计划任务脚本 install_tasks.ps1；
- 待确认：部署载体（家里常开设备 or 云服务器）——确认后执行迁移；
- 待执行：服务化（NSSM 安装）、每周冷备脚本（可选）。