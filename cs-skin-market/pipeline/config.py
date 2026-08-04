"""
Pipeline configuration — paths, DB location, csQAQ API, model parameters.
v4: csqaq.com Playwright data source.
"""

from pathlib import Path

# ---- Paths ----
ROOT_DIR = Path(__file__).resolve().parent.parent  # cs-skin-market/
DATA_DIR = ROOT_DIR / "data"
DB_PATH = DATA_DIR / "market.db"

# ---- csQAQ API ----
CSQAQ_BASE = "https://api.csqaq.com/api/v1"
API_TOKEN = "RMYAF1H7O8O4N1Q2B6J0F1F2"
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
ITEM_EXPECTANCY_STATS = {
    # 资金加权口径说明（2026-08-04）：期望按 position_limit 占仓加权（Σ(limit×ret)/Σlimit），
    # 非信号等权。当前仓位结构：panic 全 0.3、deep_value 全 0.10 → 加权=等权；
    # accumulate 混合 0.2/0.3，88 信号基准下加权与等权差异 <0.2pp。
    # 回测脚本 run_item_backtest.py / run_portfolio_backtest.py 已升级为资金加权，此层展示常量下次回放时刷新。
    # 恐慌共振 (sent>=75 + pct<10): 强信号层, 2026-08-02 回测 37信号中切片
    "panic": {
        "label": "恐慌共振",
        "n": 21,
        "win14": 95.0, "avg14": 61.4, "ci14_lo": 76.4, "ci14_hi": 99.1,
        "win30": 83.3, "avg30": 74.6,
    },
    # 周期吸筹 (sent<75 或 pct>=10): 中等信号层
    "accumulate": {
        "label": "周期吸筹",
        "n": 16,
        "win14": 81.2, "avg14": 15.1, "ci14_lo": 57.0, "ci14_hi": 93.4,
        "win30": 68.8, "avg30": 27.6,
    },
    # 深值+大盘企稳 (2026-08-04 当前引擎回放 241 信号刷新): 轻仓位 0.10
    #   一次性 hold14 +3.8% / hold30 +8.3%; 分批(首仓10%→跌10%加20%→跌15%加30%) 后 hold14 资金加权 +11.0%
    "deep_value": {
        "label": "深值企稳",
        "n": 241,
        "win14": 48.1, "avg14": 3.8, "ci14_lo": 41.8, "ci14_hi": 54.4,
        "win30": 46.1, "avg30": 8.3,
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
    "topup_ok":   {"label": "可分批补仓", "n": 448, "win14": 54.2, "avg14": 5.4, "win30": 44.0, "avg30": 5.2},
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


# ---- Transaction fees ----
FEE_RATE = 0.01         # 悠悠 1% 手续费


# ---- Category-specific thresholds (simplified P0) ----
# Override entry/exit thresholds for categories with different volatility.
# Omitted categories fall back to global defaults.