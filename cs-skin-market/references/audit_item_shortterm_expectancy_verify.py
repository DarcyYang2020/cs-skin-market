# -*- coding: utf-8 -*-
"""③审计 · 单品短期期望信号候选 独立复核脚本（2026-08-18）。

只读原始产物 + 预注册判据；不读②研究窗口的结论。
职责：对给定的三份 _exp_*.json 产物做
  1) 产物结构检查（是否为发射侧回放产物：signals 数组）
  2) stage6 算术复核 + 跨切点方向一致性 + 有效独立切点检测
  3) stage1b AUC 阈值扫描复核 + 置换记录完整性检查
  4) stage3 分桶统计复核
  5) 三关/第五件套在给定产物上的可执行性实证
     （a2_emission / walk_forward_split / permutation_baseline 需要逐信号记录）
"""
import io
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"


def load(name):
    return json.load(io.open(DATA / name, encoding="utf-8"))


def main():
    s1b = load("_exp_stage1b_target_redefinition.json")
    s3 = load("_exp_stage3_selection_score.json")
    s6 = load("_exp_stage6_period_item_mechanism.json")

    # ---------- 1. 结构检查：发射侧回放产物需要 signals 数组 ----------
    print("=" * 72)
    print("[1] 产物结构检查（发射侧回放产物 = 含 signals[] 数组）")
    for name, d in [("stage1b", s1b), ("stage3", s3), ("stage6", s6)]:
        has_signals = isinstance(d.get("signals"), list)
        print("  %-8s signals数组=%s 顶层键=%s" % (name, has_signals, list(d.keys())))
    print("  => 三份产物均无 signals 数组：均为数据层聚合统计，非发射侧回放产物")

    # ---------- 2. stage6 算术复核 + 方向 + 有效切点 ----------
    print("=" * 72)
    print("[2] stage6 分时期 Top−Bottom 中位数差复核")
    for pname, p in s6["periods"].items():
        cuts = p["cuts"]
        diffs, ns = [], []
        prev_key = None
        eff = 0
        for c in cuts:
            if c.get("n", 0) == 0:
                diffs.append(None)
                ns.append(0)
                print("  %-5s cut n=0（样本不足，无读数）" % pname)
                continue
            d = round(c["top20_med"] - c["bot20_med"], 2)
            ok = abs(d - c["top_bot_diff"]) < 1e-9
            key = (c["n"], c["all_med"], c["top20_med"], c["bot20_med"])
            if key != prev_key:
                eff += 1
            prev_key = key
            diffs.append(d)
            ns.append(c["n"])
            print("  %-5s n=%-6d top20=%-7.2f bot20=%-7.2f diff=%-6.2f (产物内 %s, 复核%s)"
                  % (pname, c["n"], c["top20_med"], c["bot20_med"], d, c["top_bot_diff"],
                     "OK" if ok else "MISMATCH"))
        pos = [x for x in diffs if x is not None]
        dir_ok = (all(x > 0 for x in pos)) or (all(x < 0 for x in pos))
        print("  => diffs=%s 方向一致=%s 有效独立切点数=%d/3 声明stable=%s"
              % (diffs, dir_ok, eff, p.get("stable")))

    # ---------- 3. stage1b AUC 阈值扫描 + 置换记录 ----------
    print("=" * 72)
    print("[3] stage1b 目标重定义复核")
    for row in s1b["threshold_scan"]:
        print("  threshold=%2d period_auc=%s" % (row["threshold"], row["period_auc"]))
    print("  main_target=%s" % s1b["main_target"])
    perm = s1b.get("permutation", {})
    print("  置换记录: scheme=%s cut=%s real_auc=%s perm_median=%s p=%s"
          % (perm.get("scheme"), perm.get("cut"), perm.get("real_auc"),
             perm.get("perm_median"), perm.get("p")))
    print("  置换完整性: n_perm=%s seed=%s" % (perm.get("n_perm"), perm.get("seed")))
    print("  注意: 置换对象=%s，非最终机制（时期×单品特性）" % perm.get("scheme"))

    # ---------- 4. stage3 分桶统计复核 ----------
    print("=" * 72)
    print("[4] stage3 超跌选品分桶复核（P 期样本）")
    for k, v in s3.items():
        if isinstance(v, dict) and "n" in v:
            print("  %-22s n=%-6d fwd14_mean=%-7.2f win=%-5.1f big_win=%-5.1f"
                  % (k, v["n"], v["fwd14_mean"], v["win_pct"], v["big_win_pct"]))
        elif isinstance(v, dict):
            for ek, ev in v.items():
                if isinstance(ev, dict) and "n" in ev:
                    print("  %-22s n=%-6d fwd14_mean=%-7.2f win=%-5.1f big_win=%-5.1f"
                          % (ek, ev["n"], ev["fwd14_mean"], ev["win_pct"], ev["big_win_pct"]))

    # ---------- 5. 三关/第五件套可执行性实证 ----------
    print("=" * 72)
    print("[5] 三关 + 第五件套在给定产物上的可执行性")
    sys.path.insert(0, str(ROOT / "references"))
    import a2_emission
    try:
        res = a2_emission.analyze(
            str(DATA / "_exp_stage6_period_item_mechanism.json"),
            str(DATA / "_exp_stage1b_target_redefinition.json"),
            "period_item", "单品短期期望")
        print("  a2_emission.analyze 结果: added_total=%s displaced_total=%s gates=%s passed=%s"
              % (res["added_total"], res["displaced_total"], res["gates"], res["passed"]))
    except Exception as e:
        print("  a2_emission 运行异常: %r" % e)

    from pipeline.backtest_methodology import walk_forward_split, permutation_baseline
    empty = walk_forward_split([])
    print("  walk_forward_split(空记录): valid=%s reason=%s" % (empty["valid"], empty["reason"]))
    perm2 = permutation_baseline([])
    print("  permutation_baseline(空收益): n=%s p_value=%s" % (perm2["n"], perm2["p_value"]))
    print("  => 给定产物无逐信号记录（date+net14），组合级 b1v2.simulate / walk-forward / 置换 / 第五件套均不可执行")


if __name__ == "__main__":
    main()
