# -*- coding: utf-8 -*-
"""I-3 存量信号族 A2 审计（2026-08-06，迭代路线图第一批）。

对现有信号族做 walk-forward + 时间聚类 + 置换检验的存量复核，
揪出「靠单一事件簇撑胜率」的族（A2 教训：全窗口均值好看 ≠ 可落地）。

数据源（只读，不重放引擎）：
- 集A data/item_backtest_latest.json：88 buy（base 46 / panic 42），官方回测基准
- 集B data/deepvalue_replay_tmp.json：301 组合回放（deep_value=limit0.10 / panic=limit0.30 / base=limit0.20）
- P1-0 供给收缩吸筹：引用 data/trend_leg_validation.json 的 S3 检验（C1 前验证已做全套 A2）

结论写入 data/legacy_audit.json，判定口径：
- 危险：聚类 flagged（单簇>50% 或 top2>80%）或 OOS test win<50% 且较 train 回落>15pp
- 警示：置换 p>=0.05 或 OOS 回落 5~15pp
- 通过：以上均无
"""
import io
import json
import sys

sys.path.insert(0, ".")
from pipeline.backtest_methodology import signal_cluster_report, walk_forward_split, permutation_baseline


def _audit_group(name, records, source, note=""):
    recs = [r for r in records if r.get("net14") is not None or r.get("net30") is not None]
    dates = [r["date"] for r in recs]
    cluster = signal_cluster_report(dates, window=3)
    out = {"name": name, "source": source, "note": note, "n": len(recs)}
    if not recs:
        out["verdict"] = "无样本"
        return out
    for field, label in (("net14", "14d"), ("net30", "30d")):
        wf = walk_forward_split(recs, anchor_ratio=0.7, return_field=field, min_samples=5)
        perm = permutation_baseline([r.get(field) for r in recs])
        out[label] = {"walk_forward": wf, "permutation": perm}
    out["cluster"] = cluster
    # ---- 判定 ----
    problems = []
    if cluster.get("flagged"):
        problems.append("聚类: " + "；".join(cluster.get("warnings", [])))
    for label in ("14d", "30d"):
        wf = out[label]["walk_forward"]
        perm = out[label]["permutation"]
        if not wf.get("valid"):
            problems.append(f"{label}: walk-forward 样本不足({wf.get('reason')})")
            continue
        tr, te = wf["train"], wf["test"]
        if te and tr and te["win_rate"] is not None and tr["win_rate"] is not None:
            drop = (tr["win_rate"] - te["win_rate"]) * 100
            if te["win_rate"] < 0.5 and drop > 15:
                problems.append(f"{label}: OOS 胜率 {te['win_rate']*100:.0f}% 较样本内回落 {drop:.0f}pp")
            elif drop > 5:
                problems.append(f"{label}: OOS 回落 {drop:.0f}pp（{tr['win_rate']*100:.0f}%→{te['win_rate']*100:.0f}%）")
        if perm.get("p_value") is not None and perm["p_value"] >= 0.05:
            problems.append(f"{label}: 置换 p={perm['p_value']:.3f} 不显著")
    if not problems:
        out["verdict"] = "通过"
    elif any("聚类" in p for p in problems) and len(problems) == 1 and "聚类" in problems[0] and cluster.get("max_cluster_share", 0) > 0.5:
        out["verdict"] = "危险-事件集中"
    else:
        out["verdict"] = "警示"
    out["problems"] = problems
    return out


def main():
    results = {}
    # ---- 集A: 88 buy ----
    a = json.load(io.open("data/item_backtest_latest.json", encoding="utf-8"))["signals"]
    for st, label in (("base", "低位低估"), ("panic", "恐慌共振")):
        recs = [dict(r) for r in a if r.get("signal_type") == st]
        results["A_" + st] = _audit_group(label, recs, "item_backtest_latest(88buy)")
    # ---- 集B: 301 组合回放 ----
    b = json.load(io.open("data/deepvalue_replay_tmp.json", encoding="utf-8"))["signals"]
    groups = {
        "deep_value": lambda r: abs(float(r.get("position_limit") or 0) - 0.10) < 0.001,
        "panic": lambda r: abs(float(r.get("position_limit") or 0) - 0.30) < 0.001,
        "base": lambda r: abs(float(r.get("position_limit") or 0) - 0.20) < 0.001,
    }
    for st, pred in groups.items():
        recs = [dict(r) for r in b if pred(r)]
        results["B_" + st] = _audit_group(st, recs, "deepvalue_replay(301)")
    # ---- P1-0: 引用 S3 检验 ----
    tv = json.load(io.open("data/trend_leg_validation.json", encoding="utf-8"))
    s3 = tv["S3"]
    results["P10"] = {
        "name": "P1-0 供给收缩吸筹",
        "source": "trend_leg_validation(S3 研究窗752/生产去重169)",
        "n": s3["signals"],
        "cluster": s3["cluster"],
        "14d": {"walk_forward": s3["walk_forward"]["14d"], "permutation": {"p_value": s3["permutation"]["14d_p"]}},
        "30d": {"walk_forward": s3["walk_forward"]["30d"], "permutation": {"p_value": s3["permutation"]["30d_p"]}},
        "problems": ["聚类: 研究窗单簇 91.5%（2026-02 事件），生产 7 天去重后 48 交易日/169 信号，仍需中性回升段复验"],
        "verdict": "警示-事件集中(已去重)",
    }
    with io.open("data/legacy_audit.json", "w", encoding="utf-8") as f:
        json.dump({"generated": "2026-08-06", "results": results}, f, ensure_ascii=False, indent=1)
    # 摘要输出
    for k, v in results.items():
        print("== %s | %s | n=%s | verdict=%s" % (k, v["name"], v.get("n"), v.get("verdict")))
        for p in v.get("problems", []):
            print("   -", p)


if __name__ == "__main__":
    main()
