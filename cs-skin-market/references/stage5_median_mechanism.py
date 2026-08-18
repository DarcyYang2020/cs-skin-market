# -*- coding: utf-8 -*-
"""阶段5：中位数期望机制（时期×时点先验 + P期超跌修正）（2026-08-18，预注册）。

定稿口径：期望值 = 中位数（非均值）；展示 7d/14d 中位数 + 翻正率 + n。
机制（层次收缩 k=20）：
  L0 全局中位数 → L1 时期中位数 → L2 时期×时点中位数 → L3（仅P期）超跌桶中位数
  每层收缩向上一层；时点超界用该时期末5日中位数（尾部渐近）。
  P期超跌分数 = -(z_chg7+z_chg3+z_z)/3，三分位桶（阈值在 train 拟合，test 用同阈值，无泄漏）。
验证：多切点 walk-forward，V1时期 / V2时期+时点 / V3时期+时点+P期超跌 的 MAE + Spearman。
输出 data/_exp_stage5_median_mechanism.json。
"""
import json
from collections import defaultdict

SRC = "data/_exp_universe_panel_v2.json"
OUT = "data/_exp_stage5_median_mechanism.json"
K = 20
CUTS = ["2025-04-01", "2025-10-01", "2026-03-01"]
FWD14 = 20


def period_code(c180, c30):
    if c30 <= -15:
        return 0
    if c180 > 0:
        return 1 if c30 > 0 else 2
    return 3 if c30 <= 0 else 4


def load_and_fix():
    d = json.load(open(SRC, encoding="utf-8"))
    rows = d["rows"]
    clean = [r for r in rows if r[3] != 0.0]
    by_date = {}
    for r in clean:
        by_date.setdefault(r[0], (r[2], r[3]))
    run_map = {}
    prev = None
    run = 0
    for dt in sorted(by_date):
        c30, c180 = by_date[dt]
        b = period_code(c180, c30)
        run = run + 1 if b == prev else 1
        prev = b
        run_map[dt] = (b, run)
    return clean, run_map


def median(v):
    v = sorted(v)
    return v[len(v) // 2]


def zscore_params(vals):
    m = sum(vals) / len(vals)
    sd = (sum((x - m) ** 2 for x in vals) / len(vals)) ** 0.5
    return m, (sd if sd > 0 else 1.0)


def spearman(xs, ys):
    n = len(xs)
    if n < 3:
        return None
    def rk(a):
        s = sorted(range(n), key=lambda i: a[i])
        r = [0] * n
        for i, p in enumerate(s):
            r[p] = i
        return r
    rx, ry = rk(xs), rk(ys)
    mx = (n - 1) / 2
    cov = sum((rx[i] - mx) * (ry[i] - mx) for i in range(n))
    vx = sum((rx[i] - mx) ** 2 for i in range(n))
    vy = sum((ry[i] - mx) ** 2 for i in range(n))
    if vx == 0 or vy == 0:
        return None
    return cov / (vx * vy) ** 0.5


class Model:
    def __init__(self, train):
        # train: [(period, day, chg7, chg3, z, fwd14)]
        self.gm = median([s[5] for s in train])
        # L1 时期
        self.pm = {}
        for p in range(5):
            v = [s[5] for s in train if s[0] == p]
            if v:
                lam = len(v) / (len(v) + K)
                self.pm[p] = lam * median(v) + (1 - lam) * self.gm
        # L2 时期×时点
        self.cm = {}
        for p in range(5):
            for day in range(1, 120):
                v = [s[5] for s in train if s[0] == p and s[1] == day]
                if v:
                    lam = len(v) / (len(v) + K)
                    self.cm[(p, day)] = lam * median(v) + (1 - lam) * self.pm.get(p, self.gm)
        # 尾部渐近（末5日中位数）
        self.tail = {}
        for p in range(5):
            days = sorted({s[1] for s in train if s[0] == p})
            if days:
                md = max(days)
                tv = [s[5] for s in train if s[0] == p and s[1] >= md - 4]
                self.tail[p] = median(tv) if tv else self.pm.get(p, self.gm)
        # L3 P期超跌桶（三分位，阈值 train 拟合）
        P = [s for s in train if s[0] == 0 and s[2] is not None and s[3] is not None and s[4] is not None]
        self.ov = {}
        self.ov_thr = None
        if len(P) >= 30:
            m7, s7 = zscore_params([s[2] for s in P])
            m3, s3 = zscore_params([s[3] for s in P])
            mz, sz = zscore_params([s[4] for s in P])
            sc = [-(((s[2] - m7) / s7) + ((s[3] - m3) / s3) + ((s[4] - mz) / sz)) / 3 for s in P]
            thr1, thr2 = sorted(sc)[len(sc) // 3], sorted(sc)[2 * len(sc) // 3]
            self.ov_thr = (m7, s7, m3, s3, mz, sz, thr1, thr2)
            buckets = defaultdict(list)
            for i, s in enumerate(P):
                b = 0 if sc[i] > thr2 else (1 if sc[i] > thr1 else 2)
                buckets[b].append(s[5])
            p_med = median([s[5] for s in P])
            for b, v in buckets.items():
                lam = len(v) / (len(v) + K)
                self.ov[b] = lam * median(v) + (1 - lam) * p_med

    def v1(self, p):
        return self.pm.get(p, self.gm)

    def v2(self, p, day):
        if (p, day) in self.cm:
            return self.cm[(p, day)]
        return self.tail.get(p, self.pm.get(p, self.gm))

    def v3(self, p, day, chg7, chg3, z):
        base = self.v2(p, day)
        if p != 0 or self.ov_thr is None or chg7 is None or chg3 is None or z is None:
            return base
        m7, s7, m3, s3, mz, sz, thr1, thr2 = self.ov_thr
        sc = -(((chg7 - m7) / s7) + ((chg3 - m3) / s3) + ((z - mz) / sz)) / 3
        b = 0 if sc > thr2 else (1 if sc > thr1 else 2)
        return self.ov.get(b, base)


def main():
    rows, run_map = load_and_fix()
    S = []
    for r in rows:
        p, day = run_map[r[0]]
        S.append((r[0], p, day, r[11], r[14], r[7], r[FWD14]))

    results = []
    for cut in CUTS:
        train = [s for s in S if s[0] < cut and s[6] is not None]
        test = [s for s in S if s[0] >= cut and s[6] is not None]
        m = Model([(s[1], s[2], s[3], s[4], s[5], s[6]) for s in train])
        actual = [s[6] for s in test]
        for name, predfn in [("V1时期", lambda s: m.v1(s[1])),
                             ("V2时期+时点", lambda s: m.v2(s[1], s[2])),
                             ("V3+P期超跌", lambda s: m.v3(s[1], s[2], s[3], s[4], s[5]))]:
            preds = [predfn(s) for s in test]
            mae = sum(abs(p - a) for p, a in zip(preds, actual)) / len(actual)
            rho = spearman(preds, actual)
            results.append({"cut": cut, "scheme": name, "mae14": round(mae, 2),
                            "spearman14": round(rho, 4) if rho else None})

    out = {"probe": "阶段5 中位数期望机制", "shrink_k": K, "cuts": CUTS, "results": results}
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("saved", OUT)
    for r in results:
        print(f"  cut={r['cut']} {r['scheme']:14s} mae14={r['mae14']:6.2f} spearman={r['spearman14']}")


if __name__ == "__main__":
    main()
