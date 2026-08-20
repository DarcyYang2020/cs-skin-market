# -*- coding: utf-8 -*-
"""族边界侦查（2026-08-20）：细族特征中心 + 无监督 KMeans 聚类（纯标准库）。

目的：不预设族，从 374 信号的特征看「现有 11 族边界是否清晰 / 信号自然聚成几类」。
只读 data/_exp_cycle_replay_fullpool_2026.json，落盘 data/_exp_family_cluster_probe_2026-08-20.json。
"""
import json
import math
import random
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "_exp_cycle_replay_fullpool_2026.json"
OUT = ROOT / "data" / "_exp_family_cluster_probe_2026-08-20.json"
POLLUTED = {"AK-47 | 流金王朝 (崭新出厂)", "挂件 | 丁烷拍档"}

d = json.load(open(SRC, encoding="utf-8"))
sigs = [s for s in d["signals"] if s["name"] not in POLLUTED]

FEATURES = ["pct", "z", "th", "sentiment", "mchg30", "mkt_drop21", "chg7", "supply_change_30d", "micro_th"]


def feats(s):
    return [s.get(f) for f in FEATURES]


def mean_std(xs):
    xs = [x for x in xs if x is not None]
    if not xs:
        return None, None
    m = sum(xs) / len(xs)
    sd = (sum((x - m) ** 2 for x in xs) / len(xs)) ** 0.5
    return round(m, 2), round(sd, 2)


# 1. 细族特征中心
by = defaultdict(list)
for s in sigs:
    by[s["action_label"]].append(s)

centers = {}
for lab, ss in by.items():
    centers[lab] = {f: mean_std([s.get(f) for s in ss]) for f in FEATURES}

# 2. 无监督 KMeans（标准库手写）
def standardize(rows):
    cols = list(zip(*rows))
    n = len(rows)
    out = []
    for c in cols:
        c = [x if x is not None else 0 for x in c]
        m = sum(c) / n
        sd = (sum((x - m) ** 2 for x in c) / n) ** 0.5 or 1.0
        out.append([(x - m) / sd for x in c])
    return list(zip(*out))


def kmeans(rows, k, seed=42, iters=200):
    rng = random.Random(seed)
    vecs = [list(r) for r in rows]
    cents = rng.sample(vecs, k)
    for _ in range(iters):
        assign = []
        for v in vecs:
            best = min(range(k), key=lambda i: sum((v[j] - cents[i][j]) ** 2 for j in range(len(v))))
            assign.append(best)
        new = []
        for i in range(k):
            mem = [vecs[j] for j in range(len(vecs)) if assign[j] == i]
            if mem:
                new.append([sum(x[j] for x in mem) / len(mem) for j in range(len(vecs[0]))])
            else:
                new.append(cents[i])
        if new == cents:
            break
        cents = new
    assign = []
    for v in vecs:
        assign.append(min(range(k), key=lambda i: sum((v[j] - cents[i][j]) ** 2 for j in range(len(v)))))
    return assign, cents


rows = []
for s in sigs:
    f = feats(s)
    rows.append([x if x is not None else 0 for x in f])
std = standardize(rows)

cluster_result = {}
for k in [4, 5, 6, 7, 8]:
    assign, cents = kmeans(std, k)
    sizes = [assign.count(i) for i in range(k)]
    # 每个簇的收益画像 + 与细族的对照
    clu = defaultdict(list)
    for s, a in zip(sigs, assign):
        clu[a].append(s)
    cluster_result[k] = {
        "sizes": sizes,
        "cluster_profiles": {
            str(i): {
                "n": len(clu[i]),
                "win14": round(sum(1 for s in clu[i] if s.get("fwd14") is not None and s["fwd14"] - 2 > 0) / max(1, len(clu[i])) * 100, 1),
                "avg14": round(sum(s.get("fwd14", 0) for s in clu[i]) / max(1, len(clu[i])), 2),
                "top_labels": dict(sorted(
                    __import__("collections").Counter(s["action_label"] for s in clu[i]).items(),
                    key=lambda kv: -kv[1])[:4]),
            } for i in range(k)
        },
    }

out = {"meta": {"date": "2026-08-20", "n": len(sigs), "features": FEATURES},
       "family_feature_centers": centers,
       "kmeans": cluster_result}
json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("saved", OUT)

# 打印细族特征中心（关键维度）
print("\n=== 细族特征中心（均值）===")
print(f"{'细族':26s} {'pct':>7s} {'z':>7s} {'th':>6s} {'sent':>6s} {'mchg30':>7s} {'drop21':>7s} {'chg7':>7s} {'sc30':>7s}")
for lab, c in centers.items():
    def g(f):
        m, _ = c[f]
        return f"{m:+.1f}" if m is not None else "  -"
    print(f"{lab[:24]:26s} {g('pct'):>7s} {g('z'):>7s} {g('th'):>6s} {g('sentiment'):>6s} {g('mchg30'):>7s} {g('mkt_drop21'):>7s} {g('chg7'):>7s} {g('supply_change_30d'):>7s}")

print("\n=== KMeans 聚类（k=5,6,7）各簇画像 ===")
for k in [5, 6, 7]:
    cr = cluster_result[k]
    print(f"--- k={k} sizes={cr['sizes']} ---")
    for ci, cp in cr["cluster_profiles"].items():
        tl = " | ".join(f"{l[:12]}:{n}" for l, n in cp["top_labels"].items())
        print(f"  簇{ci}: n={cp['n']:3d} win14={cp['win14']:5.1f}% avg14={cp['avg14']:+6.2f}  [{tl}]")
