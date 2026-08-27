#!/usr/bin/env bash
#
# cs-skin-market 一键部署脚本（Lighthouse Ubuntu 24.04）
# 用法（在目标实例上以 root 执行）:
#   bash <(curl -fsSL <本脚本URL>)         # 或把脚本传上去后 bash deploy_cs_skin_market.sh
#
# 前提：防火墙 8000 已对 0.0.0.0/0 开放（运维已提前开好）。
# 说明：不修改仓库内 run_server.py（其绑定 127.0.0.1）；本脚本用 run_prod.py 以 0.0.0.0 拉起，
#       以便公网 IP 可访问。
set -euo pipefail

# 注意：本仓库实际结构是 cs-model（根目录）内含 cs-skin-market/（应用目录）。
# GitHub 在部分国内地域直连不可达，部署改用 ghproxy 镜像代理；如网络可直连 GitHub 可改回原地址。
REPO="https://ghproxy.net/https://github.com/DarcyYang2020/cs-skin-market.git"
# 原地址（直连）: https://github.com/DarcyYang2020/cs-skin-market.git
APP_DIR="/opt/cs-skin-market/cs-skin-market"   # 应用子目录（仓库根为 cs-model）
PORT=8000

# 每日采集时间：与 Windows 计划任务 CS_Skin_DailyCollect 对齐。
# 原 Windows 任务为「北京时间 18:00」；Lighthouse 实例默认 UTC，故填 10:00（UTC）= 北京时间 18:00。
COLLECT_HOUR=10
COLLECT_MIN=00

echo "==> [1/6] 安装系统依赖（python3-venv + Playwright 运行库）"
# 说明：Playwright/Chromium 不是每日采集主路径。
# 每日 18:00 的 K线全量刷新走 csQAQ 直连 API（urllib + ApiToken，靠 bind_local_ip 绑服务器IP白名单），
# 仅当 API 返回空/401/429 时才回退 Playwright 浏览器兜底；
# 另外每周一的全市场快照/大户集中度/求购观察三项任务、以及 Web UI 的搜索并分析单品（search_good_id/fetch_item_detail）
# 才真正用浏览器。故 Chromium 必须装，但每日主负载是 API、很轻。
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y python3-venv python3-dev build-essential \
  libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
  libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 \
  libxrandr2 libgbm1 libasound2t64 libpango-1.0-0 libcairo2 fonts-liberation

echo "==> [2/6] 拉取代码"
if [ -d "$(dirname "$APP_DIR")/.git" ]; then
  git -C "$(dirname "$APP_DIR")" pull --ff-only
else
  git clone "$REPO" "$(dirname "$APP_DIR")"
fi
cd "$APP_DIR"

echo "==> [3/6] 建虚拟环境并装 Python 依赖"
if [ ! -d venv ]; then python3 -m venv venv; fi
# shellcheck disable=SC1091
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
# Chromium：仅用于 (a) K线 API 兜底 (b) 每周一快照/大户/求购三项 (c) Web UI 搜索并分析单品。
# 若只跑每日 18:00 的 API 采集、且不用 Web UI 搜索，可设 SKIP_CHROMIUM=1 跳过以省 ~150MB 内存/磁盘。
if [ "${SKIP_CHROMIUM:-0}" != "1" ]; then
  python -m playwright install chromium
  python -m playwright install-deps chromium || true   # 系统依赖兜底（上面已 apt 装，失败不阻断）
else
  echo "    [跳过] SKIP_CHROMIUM=1：不装 Chromium（每日 API 采集不受影响，但周一任务/Web UI 搜索将不可用）"
fi

echo "==> [3b] 写入鉴权 .env（AUTH-1：CS_MARKET_PASSWORD / CS_MARKET_SESSION_SECRET）"
# AUTH-1（decision-log DA 已验收关闭）为 Web UI 加了密码门禁：受保护页面/API 需登录。
# 未配置 CS_MARKET_PASSWORD 时 POST /login 会 500（设计内提示，非 bug），故部署必须注入。
# 项目 pipeline/config._load_dotenv() 启动时把 APP_DIR/.env 塞入 os.environ，写 .env 即生效（与本地一致）。
SECRET_FILE="$APP_DIR/.env"
if [ -z "${CS_MARKET_PASSWORD:-}" ]; then
  echo "    ⚠️ 未通过环境变量传入 CS_MARKET_PASSWORD（/login 将返回 500）。" >&2
  echo "    处置：① CS_MARKET_PASSWORD='你的密码' bash $0 重跑；或 ② 登录服务器手动写 $SECRET_FILE 后 systemctl restart cs-skin-market。" >&2
else
  # 不回显密码；.env 权限收紧 600，避免其他用户读取
  SESS_SECRET="${CS_MARKET_SESSION_SECRET:-$(python -c 'import secrets;print(secrets.token_hex(32))')}"
  {
    printf 'CS_MARKET_PASSWORD=%s\n' "$CS_MARKET_PASSWORD"
    printf 'CS_MARKET_SESSION_SECRET=%s\n' "$SESS_SECRET"
    # csQAQ 直连 API 令牌：采集/大盘刷新必备。缺失时 _api_call 在发请求前即报错，
    # IP 白名单形同虚设（2026-08-21 线上事故：只加了 IP 白名单、未注入 token → 大盘获取失败）。
    if [ -n "${CSQAQ_API_TOKEN:-}" ]; then
      printf 'CSQAQ_API_TOKEN=%s\n' "$CSQAQ_API_TOKEN"
    else
      echo "    ⚠️ 未传入 CSQAQ_API_TOKEN：采集/大盘刷新将失败（IP 白名单无效）。" >&2
      echo "    处置：CSQAQ_API_TOKEN='你的token' bash $0 重跑，或登录服务器手动补到 $SECRET_FILE 后 systemctl restart cs-skin-market。" >&2
    fi
    # 可选：通知 webhook（钉钉/飞书等），未传则不写
    if [ -n "${NOTIFY_WEBHOOK_URL:-}" ]; then
      printf 'NOTIFY_WEBHOOK_URL=%s\n' "$NOTIFY_WEBHOOK_URL"
    fi
    if [ -n "${NOTIFY_WEBHOOK_SECRET:-}" ]; then
      printf 'NOTIFY_WEBHOOK_SECRET=%s\n' "$NOTIFY_WEBHOOK_SECRET"
    fi
  } > "$SECRET_FILE"
  chmod 600 "$SECRET_FILE"; chown root:root "$SECRET_FILE"
  echo "    ✅ 已写入 $SECRET_FILE（权限 600；CSQAQ_API_TOKEN=$([ -n "${CSQAQ_API_TOKEN:-}" ] && echo 已注入 || echo 缺失)）"
fi

echo "==> [4/6] 写生产启动器（绑定 0.0.0.0，不改仓库代码）"
cat > "$APP_DIR/run_prod.py" <<'PY'
import sys, os
_root = os.path.dirname(os.path.abspath(__file__))
if _root not in sys.path:
    sys.path.insert(0, _root)
try:
    from pipeline import db
    db.get_conn().close()
except Exception as e:
    print("DB warm-up skipped:", e)
import uvicorn
uvicorn.run("webapp.main:app", host="0.0.0.0", port=8000, log_level="info", reload=False)
PY

echo "==> [5/6] 注册 systemd 服务（开机自启 + 崩溃重启）"
cat > /etc/systemd/system/cs-skin-market.service <<EOF
[Unit]
Description=CS Skin Market
After=network.target

[Service]
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/venv/bin/python $APP_DIR/run_prod.py
Restart=always
RestartSec=5
User=root
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable cs-skin-market
systemctl restart cs-skin-market

echo "==> [6/6] 配置每日采集 cron（替代 Windows 计划任务）"
CRON_LINE="$COLLECT_MIN $COLLECT_HOUR * * * $APP_DIR/venv/bin/python $APP_DIR/run_daily_collect.py >> $APP_DIR/daily_collect.log 2>&1"
( crontab -l 2>/dev/null | grep -v "run_daily_collect.py"; echo "$CRON_LINE" ) | crontab -

echo "DEPLOY DONE. 访问 http://<公网IP>:8000/"
