# -*- coding: utf-8 -*-
"""R2 因子注册表初始化（②算法研究窗口 · 判据 references/r2-factor-registry-prereg-2026-08-27.md）

读 R1 评估卡 data/_exp_factor_eval_2026-08-27.json → 生成 data/factor_registry.json（21 因子）。
确定性、幂等（覆盖式输出）；末尾自带 schema 校验。
状态映射（判据 §5）：候选（条件IC）→候选；候选·无增量→证伪；弱/无效→证伪；不稳定→证伪；
                待数据→待数据；条件因子→存档。
"""
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
R1 = ROOT / "data" / "_exp_factor_eval_2026-08-27.json"
OUT = ROOT / "data" / "factor_registry.json"

CATEGORY_ENUM = ("价值", "动量", "趋势", "供给", "波动", "量价", "情绪", "市场环境")
ROLE_ENUM = ("打分", "触发", "条件", "过滤")
STATUS_ENUM = ("生产", "候选", "证伪", "存档", "待数据")

# 21 因子的 definition / data_dependency / cs_note（从 R1 判据 + 引擎代码提取）
META = {
    "pct": ("pct = 90d 价格分位(0-100)（滚动窗口，fullscan_features 口径）", ["price_history.price_rmb"], "截面分位：贵/贱相对位置"),
    "z": ("z = 90d z-score（滚动窗口，fullscan_features 口径）", ["price_history.price_rmb"], "与 pct 同源，IC 相关 0.949 冗余"),
    "chg7": ("chg7 = 价格 7 日涨跌%", ["price_history.price_rmb"], "CS 反转效应：高动量品未来 14 天截面负收益"),
    "chg30": ("chg30 = 价格 30 日涨跌%", ["price_history.price_rmb"], "同上"),
    "chg90": ("chg90 = 价格 90 日涨跌%", ["price_history.price_rmb"], "同上"),
    "vol7": ("vol7 = 日收益 7 日年化波动%", ["price_history.price_rmb"], "波动因子，非线性（U 型）"),
    "vol30": ("vol30 = 日收益 30 日年化波动%", ["price_history.price_rmb"], "同上"),
    "sc7": ("sc7 = 在售量 7 日变化%", ["price_history.in_sale_count"], "供给类：条件 IC（sc30 收缩时有效）"),
    "sc30": ("sc30 = 在售量 30 日变化%", ["price_history.in_sale_count"], "供给收缩条件 IC 0.072，唯一正信号类别"),
    "s7_ratio": ("s7_ratio = 近 7 日在售均值/近 30 日在售均值（signal_tracking 口径）", ["price_history.in_sale_count"], "供给类，条件 IC"),
    "th_persistence": ("趋势健康度·持续性 0-100（trend_health 复算）", ["price_history.price_rmb"], "决策触发维度，截面 IC 非适用口径"),
    "th_steepness": ("趋势健康度·陡峭度 0-100", ["price_history.price_rmb"], "同上"),
    "th_structure": ("趋势健康度·结构(MA) 0-100", ["price_history.price_rmb"], "同上"),
    "th_supply": ("趋势健康度·供给 0-100", ["price_history.price_rmb", "price_history.in_sale_count"], "同上"),
    "th_anomaly": ("趋势健康度·异常 0-100", ["price_history.price_rmb"], "同上"),
    "sentiment": ("sentiment = approx_sentiment（价格行为代理：大跌=恐惧高分）", ["price_history.price_rmb"], "恐慌抄底逻辑 fit 段成立但增量 IC≈0=动量反转镜像"),
    "mchg7": ("mchg7 = 大盘指数 7 日涨跌%", ["market_index.value"], "市场环境：同截面常数，条件因子"),
    "mchg21": ("mchg21 = 大盘指数 21 日涨跌%", ["market_index.value"], "同上"),
    "mchg30": ("mchg30 = 大盘指数 30 日涨跌%", ["market_index.value"], "同上"),
    "spread": ("spread = price_history.price_rmb − bid_history.buy_price_max（日点差派生）", ["price_history.price_rmb", "bid_history.buy_price_max"], "盘口/流动性：bid_history 3 年全量（R1 发现）"),
    "bid": ("bid = bid_history.buy_price_max（最高买价）", ["bid_history.buy_price_max"], "买侧盘口水平"),
}

# 现有引擎因子（in_engine 标注；status=生产 的引擎因子后续由 config 校验）
ENGINE_FACTORS = {
    "pct": "打分（位置 40% 核心）",
    "z": "展示口径（v2-T13 去 z 化后仅展示）",
    "chg30": "打分+触发（动量维度）",
    "sc30": "打分（供给维度）",
    "vol30": "风险调节（概率因子）",
    "mchg30": "条件（regime 路由）",
}

VERDICT2STATUS = {
    "候选（条件IC）": "候选",
    "候选": "候选",
    "候选·无增量": "证伪",
    "弱/无效": "证伪",
    "不稳定": "证伪",
    "待数据": "待数据",
    "条件因子（regime 分段评估，不做单因子主判）": "存档",
}

# R1 评估卡 category/role 口语值 → registry 枚举（判据 §1）
CATEGORY_MAP = {
    "价值": "价值", "动量": "动量", "波动": "波动", "供给": "供给",
    "趋势": "趋势", "情绪": "情绪", "市场环境": "市场环境",
    "盘口/流动性": "供给",  # 盘口本质=流动性因子，归供给/流动性类（08-26 讨论定）
}
ROLE_MAP = {
    "打分": "打分",
    "打分+触发": "打分",      # 主角色=打分（引擎基础打分维度），触发用法进 cs_note
    "风险调节": "打分",
    "决策触发": "触发",
    "加分/过滤": "过滤",
    "条件因子": "条件",
    "流动性": "过滤",         # 流动性守卫=过滤角色
}


def quality_from_card(c):
    """R1 评估卡 → registry quality 字段（子集）"""
    q = {}
    for k in ("IC14", "IC30", "IC14_by_period", "rolling_stability", "coverage",
              "quantile_table", "cond_ic", "inc_ic", "redundant_with", "single_period_dep"):
        if c.get(k) is not None:
            q[k] = c[k]
    if c.get("verdict_note"):
        q["verdict_note"] = c["verdict_note"]
    return q or None


def build():
    r1 = json.load(open(R1, encoding="utf-8"))
    entries = []
    for c in r1["cards"]:
        fid = c["id"]
        meta = META[fid]
        status = VERDICT2STATUS.get(c["verdict"], "证伪")
        cat = CATEGORY_MAP.get(c["category"], "存档")
        role = ROLE_MAP.get(c["role"], "过滤")
        entry = {
            "id": fid,
            "name": c["name"],
            "category": cat,
            "role": role,
            "definition": meta[0],
            "data_dependency": meta[1],
            "version": "v1",
            "source": "R1 因子评估（data/_exp_factor_eval_2026-08-27.json）",
            "quality": quality_from_card(c),
            "status": status,
            "in_engine": ENGINE_FACTORS.get(fid),
            "cs_note": meta[2],
            "tested_at": "2026-08-27",
        }
        if c["role"] != role:
            entry["cs_note"] += f"（R1 原 role='{c['role']}' → registry '{role}'，主角色归一化）"
        entries.append(entry)

    doc = {
        "schema_version": 1,
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": "data/_exp_factor_eval_2026-08-27.json（R1 21 因子评估卡）",
        "count": len(entries),
        "factors": entries,
    }
    json.dump(doc, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return doc


def validate(doc):
    """判据 §1 schema 校验 + §6 验收 1/2"""
    errs = []
    ids = set()
    for f in doc["factors"]:
        if f["id"] in ids:
            errs.append(f"重复 id: {f['id']}")
        ids.add(f["id"])
        for k in ("id", "name", "definition", "data_dependency", "source"):
            if not f.get(k):
                errs.append(f"{f['id']}: 必填 {k} 缺失")
        if f["category"] not in CATEGORY_ENUM:
            errs.append(f"{f['id']}: category 越界 {f['category']}")
        if f["role"] not in ROLE_ENUM:
            errs.append(f"{f['id']}: role 越界 {f['role']}")
        if f["status"] not in STATUS_ENUM:
            errs.append(f"{f['id']}: status 越界 {f['status']}")
        if f["status"] == "生产" and not f.get("in_engine"):
            errs.append(f"{f['id']}: status=生产 但 in_engine 空")
        if f.get("quality") and not f.get("tested_at"):
            errs.append(f"{f['id']}: quality 存在但 tested_at 缺失")
    return errs


if __name__ == "__main__":
    doc = build()
    errs = validate(doc)
    print(f"registry: {doc['count']} 因子 -> {OUT}")
    print("状态分布:", {s: sum(1 for f in doc["factors"] if f["status"] == s)
                        for s in STATUS_ENUM})
    if errs:
        print("SCHEMA ERRORS:")
        for e in errs:
            print("  -", e)
        raise SystemExit(1)
    print("schema 校验: 通过")
