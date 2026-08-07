"""
Pipeline configuration — paths, DB location, csQAQ API, model parameters.
v4: csqaq.com Playwright data source.
"""

import os
from pathlib import Path

# ---- Paths ----
ROOT_DIR = Path(__file__).resolve().parent.parent  # cs-skin-market/
DATA_DIR = ROOT_DIR / "data"
# ?????? CS_MODEL_DB ???????/???????? data/market.db
DB_PATH = Path(os.environ.get("CS_MODEL_DB", str(DATA_DIR / "market.db")))

# ---- csQAQ API ----
CSQAQ_BASE = "https://api.csqaq.com/api/v1"
# ?????? CSQAQ_API_TOKEN ????? token ????/???????
API_TOKEN = os.environ.get("CSQAQ_API_TOKEN", "RMYAF1H7O8O4N1Q2B6J0F1F2")
API_RATE_LIMIT = 1.1  # seconds between calls (1 req/sec)

# ---- Four-factor model weights ----




CATEGORY_PARAMS = {
    "手套": {"mad_scale": 0.8,  "liq_floor": 5},
    "匕首": {"mad_scale": 0.8,  "liq_floor": 3},
    "步枪": {"mad_scale": 1.0,  "liq_floor": 10},
    "手枪": {"mad_scale": 1.1,  "liq_floor": 8},
    "微型冲锋枪": {"mad_scale": 1.2, "liq_floor": 6},
    "霰弹枪": {"mad_scale": 1.3, "liq_floor": 4},
    "机枪": {"mad_scale": 1.2,  "liq_floor": 3},
    "印花": {"mad_scale": 2.0,  "liq_floor": 2},
    "音乐盒": {"mad_scale": 1.5, "liq_floor": 2},
    "探员": {"mad_scale": 1.3,  "liq_floor": 3},
    "收藏品": {"mad_scale": 2.5, "liq_floor": 1},
    "武器箱": {"mad_scale": 1.8, "liq_floor": 2},
    "胶囊": {"mad_scale": 2.2,  "liq_floor": 1},
    "_default": {"mad_scale": 1.0, "liq_floor": 5},
}


# ============================================================
#  Analysis Engine Thresholds (centralized from item_analysis)
# ============================================================

# --- Percentile zones ---
Z_EXTREME_EXIT = 2.5           # >= +2.5 = extreme overbought

# --- Trend Health score bands ---
TH_STRONG = 70                 # >=70 = strong trend
TH_NEUTRAL = 50                # >=50 = neutral-to-positive
TH_WEAK = 40                   # <40 = weak/declining
THRESHOLDS = {
    # Trend Health thresholds (used by market_th.py, trend_health.py)
    "TH_STRONG": 55,
    "TH_NEUTRAL": 35,
    "TH_WEAK": 20,
}



# ============================================================
#  Experimental Features
# ============================================================
ITEM_EXIT_RULES = {
    "fear":    {"stop_pct": 0.70, "take_pct": 1.40, "hold_days": 21},
    "neutral": {"stop_pct": None, "take_pct": 1.15, "hold_days": 21},
    "greed":   {"stop_pct": 0.92, "take_pct": None, "hold_days": 21},
}


# ============================================================
#  Item price-zone expectancy labels (P1, backtest-derived)
# ============================================================
# 42 item buy signals (2026-04-21 ~ 2026-08-01, run_item_backtest.py --warmup 30).
# Shown next to price zones so investors see the mathematical expectancy of the
# signal type instead of trading on gut feeling (project principle #1/#2).
# 黑天鹅事件日历（2026-08-06，用户市场知识录入；黄盾 2025-07-16 已校准）
# 用途：信号复盘/回测统计标注「fwd 窗口与事件影响期重叠」，外生冲击不算策略负贡献；
#       实时事件风险用 settings.event_active（event_risk_coefficient），此为历史日历。
EVENT_CALENDAR = [
    {"name": "纪念品炼金", "date": "2025-05-25", "impact_days": 30, "type": "souvenir_recipe"},
    {"name": "黄盾", "date": "2025-07-16", "impact_days": 30, "type": "collection"},
    {"name": "五合一崩盘", "date": "2025-10-24", "impact_days": 35, "type": "crash"},
]

ITEM_EXPECTANCY_STATS = {
    # 口径：自动生成（references/sync_expectancy_config.py），勿手改；改回放产物后必须重跑同步。
    # 数据源：data/item_backtest_full_2025.json（去量引擎 v2（I-13 大盘 chg30>=3 深值禁买）回放 370 信号，net 已扣 2% 双边成本）。
    # events = ±3 天去簇独立事件数（J-1 口径，backtest_methodology.signal_cluster_report window=3）。
    # 展示键按单品报告 action_label 匹配：含「恐慌」→panic / 含「深值」→deep_value / 其余→accumulate。
    # win30/avg30 为 n30 口径（含 net30 信号的子集）；ci14 = Wilson 95%% 区间。
    # 历史备注：panic 旧 n=21 为 2026-08-02 强信号层切片；accumulate 旧 n=16 为短窗口切片；deep_value 旧 154 为 I-13 前，均已废弃。
    # 恐慌族：恐慌共振(46) + 恐慌退潮(46) 全量（自动生成）
    "panic": {
        "label": "恐慌族",
        "n": 92,
        "events": 2,
        "win14": 91.3, "avg14": 32.24, "ci14_lo": 83.8, "ci14_hi": 95.5,
        "win30": 78.3, "avg30": 25.47,  # n30=92
    },
    # 深值企稳：深值企稳(56) 全量（自动生成）
    "deep_value": {
        "label": "深值企稳",
        "n": 56,
        "events": 9,
        "win14": 75.0, "avg14": 14.85, "ci14_lo": 62.3, "ci14_hi": 84.5,
        "win30": 80.8, "avg30": 52.39,  # n30=52
    },
    # 吸筹族：供给收缩吸筹(166) + 基础分批(30) + 深度回调低吸(26) 全量（自动生成）
    "accumulate": {
        "label": "吸筹族",
        "n": 222,
        "events": 23,
        "win14": 61.7, "avg14": 10.72, "ci14_lo": 55.2, "ci14_hi": 67.9,
        "win30": 67.6, "avg30": 20.93,  # n30=222
    },
}
# ============================================================
#  补仓分层期望标签 (P1, 2026-08-04 全量日记录回放刷新)
# ============================================================
# 口径: 24123 条日记录回放(2025-11-02~2026-07-13, warmup=60, 只读引擎)按补仓分层条件切片,
#       逐日评估等权(补仓分批等额 1/3, 无固定单笔仓位, 不适用信号仓位加权)。
# 结论(2026-08-04): 可分批补仓条件 ∩ 融合决策buy → 14d 胜率54.2% 均值+5.40%;
#       fusion=watch 子集 14d 均值-0.30% → 补仓需融合决策放行(buy)才触发(正期望门控)。
TOPUP_EXPECTANCY_STATS = {
    # 补仓条件满足 + 融合决策 buy: 触发可分批补仓
    "topup_ok":   {"label": "可分批补仓", "n": 448, "events": 9, "win14": 54.2, "avg14": 5.4, "win30": 44.0, "avg30": 5.2},  # J-1 事件数≈9(topup_replay_p09近似复现, 2026-08-06)
    # 补仓条件满足但融合未放行: 降级暂缓
    "topup_wait": {"label": "融合未确认", "n": 394, "win14": 37.8, "avg14": -0.3, "win30": 38.2, "avg30": 4.2},
    # 半山腰 pct 25~40: 14d 期望≈0
    "halfway":    {"label": "半山腰", "n": 2437, "win14": 34.3, "avg14": -0.2},
    # 市场贪婪 sent<=30: 14d 期望为负
    "greedy":     {"label": "情绪贪婪", "n": 2841, "win14": 34.7, "avg14": -2.4},
    # 深度低估但大盘TH<45: 期望偏弱
    "mkt_weak":   {"label": "大盘未配合", "n": 409, "win14": 35.0, "avg14": -1.0},
}

# ---- 组合并发仓位上限 (P2, 2026-08-04 组合回测; 2026-08-07 v2 复验) ----
# 旧引擎 301 信号(深值241/基础20/恐慌40) hold14: 无上限并发仓位最高 12.0(=1200%, maxDD -85%) 不可行;
# 拒绝模式(恐慌>基础>深值) cap=0.8 → +54.6%/-15.3%; cap=0.6 → +39.6%/-12.9%; 等比缩放劣于拒绝模式。
# v2 复验 (data/b1_risk_validation_v2.json, 去量引擎 370 信号): cap0.8 → +193.30%/-9.39%
#   (cap0.6 → +164.49%/-8.31%)——信号质量提升直接传导至组合层, cap0.8 维持。
# 展示层预警阈值: 批量扫描中 Σ(建仓/补仓建议仓位) 超限时提示优先处理靠前信号。
PORTFOLIO_CAP_CONCURRENT = 0.8


# ---- B1 风险预算层 (2026-08-05 旧引擎验证; 2026-08-07 v2 复验 data/b1_risk_validation_v2.json) ----
# 旧引擎 301 信号: cap0.8+熔断10% -> +60.5%/-12.0% (基线 +54.6%/-15.3%, 熔断生效约18%交易日);
#   单票10%硬上限误伤 panic 仓位(+54.6→+24.6%) -> 单票只做提示不做拒绝。
# v2 复验 (去量引擎 370 信号): 组合自身 maxDD 仅 -9.39% → 熔断10% 全量 0 触发、
#   2025-11-02 子集触发 3.5% 且收益 97.88→94.95 微负 → 熔断不再作为操作建议;
#   语义转为「信号质量劣化监测器」: 实盘组合回撤若跌破 10%, 说明实盘信号质量偏离回测, 触发检查而非暂停买入。
#   dd5% 过度触发(73~85% 交易日熔断, 收益崩至 +5~11%)禁用; dd8% 子集压回撤(-14.4→-8.55)但付28pp收益, 权衡不佳仅监控。
#   单票10% 硬上限二次证伪 (cap0.8+单票10%: 全量 193.30→139.72 / 子集 97.88→82.09) -> 维持只提示。
PORTFOLIO_DRAWDOWN_BREAKER = 0.10   # 组合权益自峰值回撤阈值(监控: 信号质量劣化预警, 非操作熔断)
POSITION_CAP_SINGLE = 0.30          # 单票敞口提示阈值: (持仓市值+建议补仓)/总资产


# ---- Transaction fees ----
FEE_RATE = 0.01         # 悠悠 1% 手续费


# ---- Category-specific thresholds (simplified P0) ----
# Override entry/exit thresholds for categories with different volatility.
# Omitted categories fall back to global defaults.
# ---- 参数冻结条款 (OOS 纪律, 2026-08-07 定稿) ----
# 冻结集: 去量引擎 v2 全参数（含 I-13 大盘 chg30<=-3 深值闸门）、组合层 cap0.8、
#   单票敞口提示 30%、ITEM_EXPECTANCY_STATS 展示口径（回放同源，改回放产物后必须重跑
#   references/sync_expectancy_config.py 同步，勿手改）。
# 冻结起点: 2026-08-07（去量 v2 回放 370 信号定稿）。样本外复验窗口: 积累 ~260 天新数据
#   （约 2027-04-25 起，覆盖完整牛熊循环样本）后做真 OOS 复验。
# 复验触发（J-2 三通道，2026-08-07 修订，满足任一即启动全参数重验）:
#   A) 独立恐慌市场事件 ≥3（自然积累，不阻塞；当前 2 个）;
#   B) ~260 天新数据积累完成（约 2027-04-25）;
#   C) 胜率监测: buy 连续 2 月 14d<70% 或月度 14d<80%/30d<55%。
# 监测: python references/j2_channel_monitor.py -> data/j2_channel_status.json（dashboard 展示）。
# 冻结期内: 禁止以回放数据为依据调整冻结集内参数; 仅允许新增独立数据观察项 / 新信号族研究
#   （新族须过 A2 三件套: walk-forward + 聚类 + 置换检验，且不得改动冻结集）。
PARAM_FREEZE = {
    "frozen_at": "2026-08-07",
    "frozen_set": ["去量引擎 v2（I-13）全参数", "组合层 cap0.8", "单票敞口提示 30%", "ITEM_EXPECTANCY_STATS 展示口径"],
    "oos_revalidate_after": "2027-04-25",
    "triggers": ["A 独立恐慌市场事件≥3（当前 2，自然积累）", "B 新数据≥260 天（约 2027-04-25）", "C 胜率监测: buy 连续 2 月 14d<70% 或月度 14d<80%/30d<55%"],
    "frozen_period_note": "冻结期内禁止以回放数据为依据调参；仅允许新增独立数据观察项 / 新信号族研究（A2 三件套）",
}


# ---- J-2 重拟合触发阈值（单一事实源，Phase 0 单源化）----
# references/j2_channel_monitor.py 运行时从本字典读取，禁止在 monitor 内硬编码；
# 改阈值须同步更新 PARAM_FREEZE["triggers"] 文案，并重跑 monitor 刷新 data/j2_channel_status.json。
J2_THRESHOLDS = {
    "a_events": 3,       # A 通道: 独立恐慌市场事件数
    "b_days": 260,       # B 通道: 冻结后新数据积累天数
    "c14_month": 80.0,   # C 通道: 月度 14d 胜率阈值(%)
    "c30_month": 55.0,   # C 通道: 月度 30d 胜率阈值(%)
    "c14_2m": 70.0,      # C 通道: 连续 2 月 14d 胜率阈值(%)
}

# ---- 引擎参数版本（Phase 0 版本化）----
# signal_tracking 记录每条生产信号时的引擎版本；重拟合发布新参数时 bump，
# 使新旧引擎产生的实盘信号可区分、可分别统计。
ENGINE_VERSION = "v2-I13"  # 对应 PARAM_FREEZE.frozen_set 首项: 去量引擎 v2（I-13）全参数
