# -*- coding: utf-8 -*-
"""D6 oos_zone 禁区守卫（2026-08-27）。

研究/评估脚本在研究准入前必须声明是否触碰样本外
（date >= OOS_ZONE["val_start"] 或 >= b_channel_start）。
无预注册判据触碰禁区 → raise RuntimeError 拦截（防幸存者偏差/反过拟合）。
仅加元数据约束，不删数据、不影响采集层。
"""
from .config import OOS_ZONE


def in_oos_zone(date_str):
    """date_str 是否落在样本外禁区（>= val_start）。"""
    return (date_str or "") >= OOS_ZONE["val_start"]


def require_fit(date_str, prereg=None, label=""):
    """研究脚本入口守卫：窗口 date_str 必须 < val_start（fit 段）。

    若触碰样本外且未提供预注册判据 id（prereg）→ raise 拦截。
    返回 date_str 以便链式调用。
    """
    if in_oos_zone(date_str) and not prereg:
        raise RuntimeError(
            f"oos_zone 禁区拦截：{label or date_str} 落在验证段(>={OOS_ZONE['val_start']})，"
            f"须先预注册判据（prereg）方可触碰")
    return date_str
