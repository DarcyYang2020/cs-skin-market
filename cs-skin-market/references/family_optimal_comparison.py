# -*- coding: utf-8 -*-
"""最优划分 · 逐族对照差异表（2026-08-20，②；CP §六/§八 承诺产物）

读 _exp_optimal_partition_2026-08-20.json 的 21 候选族，做：
1. 精确归类（修正三处漂移：leaf21→深跌反弹右侧、leaf18→企稳供扩、rare_lowpct_leaf21→深值+大盘上行边界）；
2. 分级标签 + 事件驱动型判定（该留=事件驱动走事件级验证；该加=单事件簇触否决线）；
3. 逐族对照差异表（现有 11 族 vs 数据 4 大类，unobserved_dims 标注）。
产物：data/_exp_optimal_partition_comparison_2026-08-20.json
"""
import json

D = json.load(open("data/_exp_optimal_partition_2026-08-20.json", encoding="utf-8"))
passed = D["passed"]


def classify(r):
    c = r["centroid"]
    # 深跌反弹右侧：反弹（chg7>0）且大盘深跌
    if c["chg7"] > 0 and c["mchg21"] < -18:
        return "深跌反弹右侧"
    # 恐慌深跌：单品深跌（chg30<-28 或 chg7<-20）且大盘深跌
    if (c["chg30"] < -28 or c["chg7"] < -20) and c["mchg21"] < -18:
        return "恐慌深跌"
    # 大盘30日上涨：pct 中高=牛市/强势上行，低=深值+大盘上行
    if c["mchg30"] > 0:
        return "牛市/强势上行" if c["pct"] >= 40 else "深值+大盘上行"
    # 大盘30日非涨：低 pct=深值慢修复，中高=企稳/深跌中位
    return "深值慢修复" if c["pct"] < 40 else "企稳/深跌中位"


groups = {}
for r in passed:
    g = classify(r)
    groups.setdefault(g, []).append(r)

# 现有 11 族对照表（unobserved_dims 标注）
FAMILIES = [
    {"key": "panic_resonance", "label": "恐慌共振", "on": True,
     "unobserved": ["micro_th", "sent", "current"], "match": "恐慌深跌"},
    {"key": "panic_easing", "label": "恐慌退潮", "on": True,
     "unobserved": ["sent", "stopped"], "match": "恐慌深跌"},
    {"key": "deep_value", "label": "深值企稳", "on": True,
     "unobserved": ["th", "market_th", "sent"], "match": "深值慢修复"},
    {"key": "supply_accum", "label": "供给收缩吸筹", "on": True,
     "unobserved": ["s7/s30 均值", "sent", "market_th", "chg8"], "match": "无（横盘供缩未切出正期望区）"},
    {"key": "rise_accum", "label": "吸筹型上涨", "on": True,
     "unobserved": ["s7/s30 均值", "market_th"], "match": "牛市/强势上行（单品维度，非大盘维度）"},
    {"key": "rise_contract", "label": "深收缩慢涨", "on": False,
     "unobserved": ["s7/s30 均值", "market_th"], "match": "牛市/强势上行（sc30≤-5 供缩上涨有对应）"},
    {"key": "rs_accum", "label": "相对强度", "on": False,
     "unobserved": ["RS30 相对维度（数据切分用绝对 mchg 未切）"], "match": "未切出（相对维度缺失）"},
    {"key": "ct_accum", "label": "逆市走强", "on": False,
     "unobserved": ["逆市相对维度"], "match": "未切出（相对维度缺失）"},
    {"key": "volatile_accum", "label": "震荡吸筹", "on": False,
     "unobserved": ["vol7 单位（原始std vs 年化%）"], "match": "未切出"},
    {"key": "second_wave", "label": "二波回调", "on": False,
     "unobserved": ["mkt180", "dd20", "dd20_age", "bid"], "match": "未切出（dd20 维度缺失）"},
    {"key": "xishou_mid", "label": "惜售中段", "on": False,
     "unobserved": ["s7/s30 均值", "chg5", "sent", "market_th"], "match": "部分（chg7 跌 + pct 中段）"},
]

comparison = {
    "meta": {"date": "2026-08-20", "n_passed": len(passed),
             "note": "sc30 符号非新发现——实为引擎 trend_health._dim_supply_price 已有语义（涨+供缩=吸筹/跌+供扩=抛压）的引擎独立验证"},
    "groups": {},
    "family_comparison": [],
}

for g in ["牛市/强势上行", "恐慌深跌", "深值慢修复", "深值+大盘上行", "企稳/深跌中位", "深跌反弹右侧", "其他"]:
    if g not in groups:
        continue
    rs = sorted(groups[g], key=lambda x: -x["n"])
    comparison["groups"][g] = [{
        "source": r["source"], "n": r["n"], "grade": r["grade"],
        "event": r["event"], "hit": r["engine_hits"],
        "centroid": r["centroid"], "rule": r["rule"],
        "note": ("事件驱动型（该留，走事件级验证）" if g in ("恐慌深跌",)
                 or (g == "深值慢修复" and r["grade"] == "单事件簇") else
                 ("已驳回（单事件簇，A2 否决线，关联 CE crash_vol 证伪）" if g == "深跌反弹右侧" else ""))
    } for r in rs]

for f in FAMILIES:
    comparison["family_comparison"].append({
        "key": f["key"], "label": f["label"], "default_on": f["on"],
        "unobserved_dims": f["unobserved"], "data_match": f["match"],
        "verdict": "该留" if f["match"] in ("恐慌深跌", "深值慢修复") else
                   ("该加（大盘上行段盲区，须高选择性；关联 CE bull_steady 证伪）" if f["key"] == "rise_accum" else
                    ("待补维度（不判删）" if not f["on"] or f["key"] == "supply_accum" else "待补维度"))
    })

json.dump(comparison, open("data/_exp_optimal_partition_comparison_2026-08-20.json", "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)

print("=== 4 大类归类（修正后）===")
for g, rs in comparison["groups"].items():
    print(f"{g}: {sum(r['n'] for r in rs)} 条 / {len(rs)} 候选")
    for r in rs:
        c = r["centroid"]
        print(f"   {r['source']:20s} n={r['n']:6d} grade={r['grade']:6s} hit={r['hit']:3d} | pct{c['pct']:.0f} chg7{c['chg7']:+.1f} mchg21{c['mchg21']:+.1f} mchg30{c['mchg30']:+.1f} sc30{c['sc30']:+.1f} {r['note']}")
print("\n=== 逐族对照差异表 ===")
for f in comparison["family_comparison"]:
    print(f"  {f['label']:8s} [{f['key']:14s}] 默认{'开' if f['default_on'] else '关'} → {f['verdict']}  | unobserved={f['unobserved_dims']}")
print("\nsaved data/_exp_optimal_partition_comparison_2026-08-20.json")
