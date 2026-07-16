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
WEIGHT_SCARCITY  = 0.35
WEIGHT_VOLUME    = 0.25
WEIGHT_LIQUIDITY = 0.15
WEIGHT_MARKET    = 0.25

# ---- Grade thresholds ----
GRADE_THRESHOLDS = {
    "S": 3.5,
    "A": 2.5,
    "B": 1.5,
    "C": 0.0,
}

# ============================================================
#  FACTOR 1: Scarcity
# ============================================================
RARITY_COEF = {
    "contraband": 5.0,
    "covert": 3.0,
    "classified": 2.0,
    "restricted": 1.5,
    "mil-spec": 1.0,
    "industrial": 0.5,
    "consumer": 0.2,
}

SOURCE_MULTIPLIER = {
    "collection": 1.5,
    "case": 1.0,
    "discontinued_case": 2.0,
    "discontinued_long": 3.5,
    "current_case": 0.8,
}

# ============================================================
#  FACTOR 2: Volume (daily transaction count)
# ============================================================
VOLUME_SCORES = [
    (100, float("inf"), 1.30),
    (30,  100,          1.10),
    (10,  30,           1.00),
    (1,   10,           0.70),
    (0,   1,            0.40),
]

# ============================================================
#  FACTOR 3: Liquidity (order-book health)
# ============================================================
LIQUIDITY_SPREAD_SCORES = [
    (0,  2,   1.3),
    (2,  5,   1.1),
    (5,  10,  1.0),
    (10, 20,  0.7),
    (20, float("inf"), 0.4),
]

LIQUIDITY_DEPTH_SCORES = [
    (3.0, float("inf"), 1.3),
    (1.0, 3.0,         1.1),
    (0.5, 1.0,         1.0),
    (0.1, 0.5,         0.7),
    (0.0, 0.1,         0.4),
]

# ============================================================
#  FACTOR 4: Market index
# ============================================================
MARKET_SCORES = [
    (5.0,  float("inf"),  1.20),
    (0.0,  5.0,           1.05),
    (-1.0, 0.0,           1.00),
    (-5.0, -1.0,          0.90),
    (float("-inf"), -5.0, 0.75),
]

# ============================================================
#  MODIFIER: Sector heat
# ============================================================
SECTOR_RANK_MODIFIER = [
    (1,  0.20),
    (2,  0.12),
    (3,  0.05),
    (4,  0.00),
    (5,  -0.05),
    (6,  -0.10),
    (999, -0.15),
]

# ============================================================
#  MODIFIER: Momentum signals
# ============================================================
VOLUME_SPIKE_MODIFIER = [
    (5.0, float("inf"), 0.25),
    (3.0, 5.0,          0.15),
    (2.0, 3.0,          0.08),
    (0.5, 2.0,          0.00),
    (0.0, 0.5,          -0.05),
]

# ============================================================
#  MODIFIER: Event overlay
# ============================================================
EVENT_MODIFIERS = {
    "major_tournament":   {"window_days": 14, "before": 0.08, "during": 0.05, "after": -0.03},
    "new_case_release":   {"window_days": 21, "before": 0.00, "during": -0.10, "after": 0.05},
    "steam_sale":         {"window_days": 10, "before": 0.00, "during": -0.08, "after": 0.10},
    "cs2_major_update":   {"window_days": 30, "before": 0.10, "during": 0.15, "after": 0.05},
    "youpin_promo":       {"window_days": 7,  "before": 0.05, "during": 0.10, "after": -0.05},
    "collection_retire":  {"window_days": 365,"before": 0.00, "during": 0.30, "after": 0.00},
}

ACTIVE_EVENTS = [
    # {"type": "major_tournament", "start": "2026-07-15", "end": "2026-07-28", "label": "BLAST Major"},
]

# ============================================================
#  Stop-loss / Take-profit
# ============================================================
TAKE_PROFIT_STEPS = [
    (0.20, 0.25),
    (0.35, 0.25),
    (0.50, 0.25),
    (0.80, 1.0),
]

STOP_LOSS_STEPS = [
    (-0.10, 0.0),
    (-0.15, 0.50),
    (-0.25, 1.0),
]

# ============================================================
#  Known sectors (csQAQ chg_type_data categories)
# ============================================================
KNOWN_SECTORS = [
    "手套", "匕首", "步枪", "手枪", "微型冲锋枪", "霰弹枪",
    "印花", "音乐盒", "探员", "武器箱", "收藏品", "新晋热门",
]

# ============================================================
#  Category Parameters for Trend Health & Supply Analysis
# ============================================================
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
PCT_UNDERVALUED_MAX = 30       # <=30% = undervalued
PCT_FAIR_MAX = 70              # <=70% = fair / neutral
PCT_OVERVAULED_MIN = 70        # >70% = overvalued / bubble
PCT_EXTREME_BUBBLE = 90        # >90% = extreme bubble warning

# --- Z-score signals ---
Z_ENTRY_MAX = -1.5             # <= -1.5 = oversold / entry signal
Z_EXIT_MIN = 2.0               # >= +2.0 = overbought / exit signal
Z_EXTREME_EXIT = 2.5           # >= +2.5 = extreme overbought

# --- Trend Health score bands ---
TH_STRONG = 70                 # >=70 = strong trend
TH_NEUTRAL = 50                # >=50 = neutral-to-positive
TH_WEAK = 40                   # <40 = weak/declining
TH_VERY_WEAK = 20              # <20 = very weak

# --- Volume stability thresholds ---
VOL_STABLE_MIN = 0.8           # avg_vol within 80% of median = stable
VOL_VOLATILE_MAX = 2.0         # avg_vol > 2x median = volatile
VOL_EXTREME_MAX = 2.5          # > 2.5 = extreme volatility

# --- Cycle detection ---
CYCLE_CONFIDENCE_BASE = 35     # base confidence for weak signals
CYCLE_CONFIDENCE_MEDIUM = 55   # medium confidence
CYCLE_CONFIDENCE_HIGH = 60     # high confidence

# --- Whale detection ---
WHALE_RANGE_TIGHT = 5.0        # <=5% price range = tight (position locking)
WHALE_CONSECUTIVE_CLOSE = 5    # >=5 consecutive closes near same level

# --- Supply analysis ---
SUPPLY_VOLUME_LOW = 100        # <100 total volume = low supply score
SUPPLY_VOLUME_MED = 200        # <200 = medium
SUPPLY_VOLUME_HIGH = 500       # >=500 = high
