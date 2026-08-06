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
    # 口径（2026-08-06 K-2 引擎 458 信号重算（C2 deep_value 阴跌闸门），data/item_backtest_full_2025.json，net 已扣 2% 双边成本）：
    # events = ±3 天去簇独立事件数（J-1 口径，backtest_methodology.signal_cluster_report window=3）。
    # 展示键按单品报告 action_label 匹配：含「恐慌」→panic / 含「深值」→deep_value / 其余→accumulate。
    # 恐慌族 = 恐慌共振(45) + 恐慌退潮(47) 全量（旧 n=21 为 2026-08-02 强信号层切片，已废弃）
    "panic": {
        "label": "恐慌族",
        "n": 92,
        "events": 2,
        "win14": 91.3, "avg14": 33.4, "ci14_lo": 83.8, "ci14_hi": 95.5,
        "win30": 79.3, "avg30": 25.8,
    },
    # 吸筹族 = 供给收缩吸筹(163) + 深度回调低吸(31) + 基础分批(6) 全量（旧 n=16 为短窗口切片，已废弃）
    "accumulate": {
        "label": "吸筹族",
        "n": 212,
        "events": 23,
        "win14": 58.8, "avg14": 9.9, "ci14_lo": 52.1, "ci14_hi": 65.4,
        "win30": 65.9, "avg30": 20.7,
    },
    # 深值+大盘企稳（K-2 供给扩张闸门 + C2 阴跌闸门后 154 信号，轻仓 0.10；旧 211 信号为阴跌闸门前）
    "deep_value": {
        "label": "深值企稳",
        "n": 154,
        "events": 28,
        "win14": 57.0, "avg14": 7.3, "ci14_lo": 49.1, "ci14_hi": 65.0,
        "win30": 61.7, "avg30": 20.9,
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

# ---- 组合并发仓位上限 (P2, 2026-08-04 组合回测) ----
# 301 信号(深值241/基础20/恐慌40) hold14 组合模拟: 无上限并发仓位最高 12.0(=1200%, maxDD -85%)
# 不可行; 拒绝模式(恐慌>基础>深值) cap=0.8 → 总收益+54.6% maxDD-15.3% 利用率63%;
# cap=0.6 → +39.6%/-12.9%; 等比缩放仓位方案在各级别均劣于拒绝模式。
# 展示层预警阈值: 批量扫描中 Σ(建仓/补仓建议仓位) 超限时提示优先处理靠前信号。
PORTFOLIO_CAP_CONCURRENT = 0.8


# ---- B1 风险预算层 (2026-08-05 回测验证, data/b1_risk_validation.json) ----
# 301 信号组合回放: cap0.8 基线 总收益+54.6%/maxDD-15.3%;
# cap0.8 + 组合回撤熔断10%(权益自峰值回撤10%暂停新信号, 收复峰值解除) -> +60.5%/-12.0%, 熔断生效约18%交易日;
# 熔断15%+ 几乎不触发(无效); 单票10%硬上限误伤 panic 0.3 仓位(收益跌至+24.6%) -> 单票只做提示不做拒绝。
PORTFOLIO_DRAWDOWN_BREAKER = 0.10   # 组合权益自峰值回撤阈值(熔断建议)
POSITION_CAP_SINGLE = 0.30          # 单票敞口提示阈值: (持仓市值+建议补仓)/总资产


# ---- Transaction fees ----
FEE_RATE = 0.01         # 悠悠 1% 手续费


# ---- Category-specific thresholds (simplified P0) ----
# Override entry/exit thresholds for categories with different volatility.
# Omitted categories fall back to global defaults.