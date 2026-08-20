# -*- coding: utf-8 -*-
"""③审计 复审复核 v2：单品短期期望信号候选（复审版，2026-08-18）。

只读原始产物 + 预注册判据（修订版落地规格）；不读②结论。
独立复核：
  1) stage9 结构（val 段日期 ≥ SPLIT、n 与 stage8 val_n 匹配、字段完整性）
  2) 按 period 用 stage9 逐行数据重算 spearman_base/spearman_on/topbot（对 stage8）
  3) val 段独立置换（打乱 trait 标签，n_perm=500, seed=42）→ p
  4) 前后半段一致：stage6 cut1（样本内）方向 vs stage8 val 方向（注明嵌套窗口重叠）
  5) stage7 可溯源性（P 对齐 stage6 cut1；S1/S2/S3 无法从给定产物溯源）
  6) 严格 a2_emission / b1v2 可执行性（所需字段检查）
"""
import io
import json
import random
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SPLIT = "2025-08-10"


def load(name):
    return json.load(io.open(DATA / name, encoding="utf-8"))


def rank(vals):
    order = sorted(range(len(vals)), key=lambda i: vals[i])
    ranks = [0.0] * len(vals)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and vals[order[j + 1]] == vals[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def pearson(x, y):
    n = len(x)
    mx, my = sum(x) / n, sum(y) / n
    cov = sum((a - mx) * (b - my) for a, b in zip(x, y))
    vx = sum((a - mx) ** 2 for a in x)
    vy = sum((b - my) ** 2 for b in y)
    if vx == 0 or vy == 0:
        return 0.0
    return cov / (vx ** 0.5 * vy ** 0.5)


def spearman(x, y):
    return pearson(rank(x), rank(y))


def med(vals):
    s = sorted(vals)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


def topbot_median(fwd, score):
    n = len(fwd)
    k = max(1, n // 5)
    idx = sorted(range(n), key=lambda i: score[i])
    return med([fwd[i] for i in idx[-k:]]) - med([fwd[i] for i in idx[:k]])


def main():
    s9 = load("_exp_stage9_emission_signals.json")
    s8 = load("_exp_stage8_emission.json")
    s7 = load("_exp_stage7_permutation.json")
    s6 = load("_exp_stage6_period_item_mechanism.json")

    print("=" * 74)
    print("[1] stage9 结构")
    sig = s9["signals"]
    print("  n_signals 声明=%s 实际=%d" % (s9["n_signals"], len(sig)))
    dates = [r["date"] for r in sig]
    print("  日期范围 %s ~ %s; SPLIT 前行数=%d（val 段应=0）"
          % (min(dates), max(dates), sum(1 for d in dates if d < SPLIT)))
    print("  fwd14_actual 缺失=%d" % sum(1 for r in sig if r.get("fwd14_actual") is None))
    from collections import Counter
    codes = Counter(r["period"] for r in sig)
    print("  period 码分布:", dict(codes))

    # period 码 → 时期名：按 val_n 匹配 stage8
    name_by_code = {}
    for code in codes:
        rows = [r for r in sig if r["period"] == code]
        n = len(rows)
        matches = [pn for pn, pv in s8["periods"].items() if pv["val_n"] == n]
        name_by_code[code] = matches[0] if len(matches) == 1 else ("未知(%s)" % n)
        print("  period=%s -> %s (n=%d)" % (code, name_by_code[code], n))

    print("=" * 74)
    print("[2] 用 stage9 重算 stage8（val 段）")
    print("  %-6s | %6s | %10s %10s | %10s %10s | %8s %8s | %8s %8s" % (
        "时期", "n", "sp_base", "sp_on", "topbot_base", "topbot_on",
        "sp_base", "sp_on", "tb_base", "tb_on"))
    print("  %-6s | %6s | %10s %10s | %10s %10s | %8s %8s | %8s %8s" % (
        "", "", "(stage8)", "(stage8)", "(stage8)", "(stage8)",
        "(复算)", "(复算)", "(复算)", "(复算)"))
    all_ok = True
    for code, pname in sorted(name_by_code.items(), key=lambda kv: str(kv[0])):
        rows = [r for r in sig if r["period"] == code]
        fwd = [r["fwd14_actual"] for r in rows]
        pb = [r["pred_base"] for r in rows]
        po = [r["pred_on"] for r in rows]
        tr = [r["trait_score"] for r in rows]
        st = s8["periods"].get(pname, {})
        r_sp_b = round(spearman(pb, fwd), 4)
        r_sp_o = round(spearman(po, fwd), 4)
        r_tb_b = round(topbot_median(fwd, pb), 2)
        r_tb_o = round(topbot_median(fwd, tr), 2)
        o_sp_b = st.get("spearman_base")
        o_sp_o = st.get("spearman_on")
        o_tb_b = st.get("topbot_base")
        o_tb_o = st.get("topbot_on")
        ok = (abs(r_sp_b - o_sp_b) < 0.005 and abs(r_sp_o - o_sp_o) < 0.005
              and abs(r_tb_b - o_tb_b) < 0.1 and abs(r_tb_o - o_tb_o) < 0.1)
        all_ok = all_ok and ok
        print("  %-6s | %6d | %10s %10s | %10s %10s | %8s %8s | %8s %8s  %s" % (
            pname, len(rows), o_sp_b, o_sp_o, o_tb_b, o_tb_o,
            r_sp_b, r_sp_o, r_tb_b, r_tb_o, "OK" if ok else "MISMATCH"))
    print("  => stage8 全部字段复算匹配=%s" % all_ok)

    print("=" * 74)
    print("[3] val 段独立置换（打乱 trait 标签，n_perm=500, seed=42）")
    rng = random.Random(42)
    for code, pname in sorted(name_by_code.items(), key=lambda kv: str(kv[0])):
        rows = [r for r in sig if r["period"] == code]
        fwd = [r["fwd14_actual"] for r in rows]
        tr = [r["trait_score"] for r in rows]
        real = topbot_median(fwd, tr)
        hits = 0
        perm_diffs = []
        for _ in range(500):
            sh = tr[:]
            rng.shuffle(sh)
            d = topbot_median(fwd, sh)
            perm_diffs.append(d)
            if d >= real:
                hits += 1
        p_hits = hits / 500.0
        p_conv = (hits + 1) / 501.0
        print("  %-6s n=%-6d real_topbot=%-7.2f perm_median=%-6.2f perm_p90=%-6.2f "
              "p(hits/500)=%.4f p((hits+1)/501)=%.4f"
              % (pname, len(rows), real, med(perm_diffs),
                 sorted(perm_diffs)[int(500 * 0.9) - 1], p_hits, p_conv))

    print("=" * 74)
    print("[4] 前后半段一致：样本内(stage6 cut1) 方向 vs val(stage8/9) 方向")
    for pname in s6["periods"]:
        cut1 = s6["periods"][pname]["cuts"][0]
        if cut1.get("n", 0) == 0:
            print("  %-6s cut1 n=0" % pname)
            continue
        v = s8["periods"][pname]
        print("  %-6s 样本内cut1(2025-04-01) diff=%6.2f (n=%d) | val topbot_on=%6.2f | "
              "val spearman_on=%7.4f | 方向%s"
              % (pname, cut1["top_bot_diff"], cut1["n"], v["topbot_on"],
                 v["spearman_on"], "一致" if (cut1["top_bot_diff"] > 0) == (v["topbot_on"] > 0) else "相反"))
    print("  注意: stage6 三个 cut 为嵌套窗口（n 随 cut 后移递减），非独立样本；"
          "P 的 cut1 n=4095 ≈ val 4004，样本高度重叠")

    print("=" * 74)
    print("[5] stage7 可溯源性")
    for pname, p in s7["periods"].items():
        s6c1 = s6["periods"].get(pname, {}).get("cuts", [{}])[0]
        s8v = s8["periods"].get(pname, {})
        print("  %-6s stage7 n=%-6d D_real=%-6.2f (对齐 stage6 cut1=%s / stage8 val_n=%s)"
              % (pname, p["n"], p["D_real"],
                 "一致" if abs(p["D_real"] - s6c1.get("top_bot_diff", -999)) < 0.01
                 else "不一致(cut1=%.2f)" % s6c1.get("top_bot_diff", float("nan")),
                 s8v.get("val_n")))
    print("  stage7 顶层字段:", list(s7.keys()), "（无 seed / p 计算方法字段）")

    print("=" * 74)
    print("[6] 严格 第五件套 / 组合级 可执行性")
    req_a2e = {"date", "name", "action_label", "net14", "net30"}
    print("  a2_emission 所需字段缺失:", sorted(req_a2e - set(sig[0].keys())))
    print("  b1v2.simulate 所需: date+fwd价格路径+st/prio —— stage9 仅 fwd14_actual 标量，不可执行")
    print("  => 严格 a2_emission / b1v2 在给定产物上仍不可运行；"
          "发射侧证据采用修订规格 §四 的适配检验（stage8/9 + 上述复算/置换）")


if __name__ == "__main__":
    main()
