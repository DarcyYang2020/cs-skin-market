# -*- coding: utf-8 -*-
"""DISPLAY-2 单品短期期望 · 在线纯展示函数（2026-08-18，审计通过后落地）。

纯展示，不进决策、不 bump ENGINE_VERSION。查表 data/_exp_shortterm_table.json
（walk-forward train 拟合、版本化）。机制见 references/build_shortterm_table.py：
  E_item(P/S1/S2) = 特性桶中位数；E_base(S3/S4) = 时期×时点先验（时点超界→末5日中位数）。
"""
import io
import json
import os
import time
from pathlib import Path

_TABLE_PATH = Path(__file__).resolve().parent.parent / "data" / "_exp_shortterm_table.json"
_CACHE = {"ts": 0.0, "data": None}

_PERIOD_NAME_TO_CODE = {
    "P恐慌深跌": 0, "S1牛市上行": 1, "S2牛市回调": 2, "S3弱市阴跌": 3, "S4弱市反弹": 4,
    # 兼容短名
    "P恐慌": 0, "S1牛市": 1, "S2回调": 2, "S3阴跌": 3, "S4反弹": 4,
}

# 特性启用期（③审计#2 落地条件 2：仅 P/S1/S2；S3 趋势特性样本外失效、S4 无信号，均不启用）
_TRAIT_ENABLED = {0, 1, 2}
_BUCKET_LABEL = {0: "偏强", 1: "中", 2: "偏弱"}


def _load_table():
    now = time.time()
    if _CACHE["data"] is None or now - _CACHE["ts"] > 300:
        with io.open(_TABLE_PATH, "r", encoding="utf-8") as f:
            _CACHE["data"] = json.load(f)
        _CACHE["ts"] = now
    return _CACHE["data"]


def _to_code(period):
    if isinstance(period, int):
        return period if 0 <= period <= 4 else None
    return _PERIOD_NAME_TO_CODE.get(str(period))


def compute_shortterm_expectancy(period, period_days, chg7, chg3, z, th, supply30):
    """计算单品短期期望（纯展示，不进决策）。

    返回 dict（供展示层渲染）或 None（输入不足/查表缺失/任何异常）。
    """
    try:
        code = _to_code(period)
        if code is None or period_days is None:
            return None
        table = _load_table()
        p = (table.get("periods") or {}).get(str(code))
        if not p:
            return None
        name = p.get("name") or str(period)

        # ---- 分时期单品特性（仅 P/S1/S2） ----
        trait = p.get("trait")
        if code in _TRAIT_ENABLED and trait:
            zp = trait.get("z_params") or {}
            def _z(x, key):
                if x is None or key not in zp:
                    return 0.0
                m, sd = zp[key]
                return (x - m) / sd if sd else 0.0
            if code == 0:
                score = -(_z(chg7, "c7") + _z(chg3, "c3") + _z(z, "z")) / 3
            else:
                score = -_z(supply30, "s30")
            thr1, thr2 = trait.get("thr1"), trait.get("thr2")
            if thr1 is None or thr2 is None:
                return None
            b = 0 if score > thr2 else (1 if score > thr1 else 2)
            cell = (trait.get("buckets") or {}).get(str(b))
            if not cell:
                return None
            return {
                "period": name,
                "period_days": period_days,
                "fwd7": cell.get("fwd7"),
                "fwd14": cell.get("fwd14"),
                "trait_note": "{}（{}期，本品{}）".format(trait.get("feature", ""), name, _BUCKET_LABEL[b]),
                "source": "trait",
            }

        # ---- S3/S4：只用时期×时点先验 ----
        by_day = p.get("prior_by_day") or {}
        cell = by_day.get(str(period_days))
        if cell:
            return {
                "period": name,
                "period_days": period_days,
                "fwd7": cell.get("fwd7"),
                "fwd14": cell.get("fwd14"),
                "trait_note": "{}（{}期，无单品特性，只用时期×时点先验）".format(name, name),
                "source": "prior",
            }
        tail = p.get("tail") or {}
        return {
            "period": name,
            "period_days": period_days,
            "fwd7": tail.get("fwd7"),
            "fwd14": tail.get("fwd14"),
            "trait_note": "{}（{}期，时点超界取末5日先验，无单品特性）".format(name, name),
            "source": "prior_tail",
        }
    except Exception:
        return None


def shortterm_expectancy_text(period, period_days, chg7, chg3, z, th, supply30):
    """渲染为报告文案（纯展示，历史同态·非本次预测）。返回字符串或 None。"""
    r = compute_shortterm_expectancy(period, period_days, chg7, chg3, z, th, supply30)
    if not r or not r.get("fwd14") or r["fwd14"].get("med") is None:
        return None
    f7 = r.get("fwd7") or {}
    f14 = r.get("fwd14") or {}
    def _cell(c):
        if not c or c.get("med") is None:
            return None
        win = c.get("win")
        win_txt = "{}%".format(win) if win is not None else "n/a"
        return "+{:.1f}% · 翻正率 {}（n={}）".format(c["med"], win_txt, c.get("n") or 0)
    parts = ["短期期望（历史同态·非本次预测）", "当前市场：{}（进入第 {} 天）".format(r["period"], r["period_days"])]
    c7, c14 = _cell(f7), _cell(f14)
    if c7:
        parts.append("7d 期望  " + c7)
    if c14:
        parts.append("14d 期望 " + c14)
    parts.append("本品特性：" + (r.get("trait_note") or ""))
    return "；".join(parts)
