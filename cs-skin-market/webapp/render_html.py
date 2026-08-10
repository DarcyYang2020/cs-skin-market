# -*- coding: utf-8 -*-
"""Python f-string HTML 渲染集中模块（C-1 拆模块第一批，2026-08-10）。

从 webapp/main.py 切出的纯渲染函数：不依赖 FastAPI app/request/templates，
可独立单测（t_render_html）。Jinja 模板之外的 Python 侧 HTML 拼装集中于此；
batch_scan.build_scan_html 属 batch_scan 域暂留原处（C-1 另一半=迁 Jinja 未做）。
"""
from pipeline import db


def spark_svg(pts, cost):
    """行内走势图：30日价格折线 + 成本线（纯展示，不触碰任何信号）。"""
    if not pts or len(pts) < 2:
        return ""
    W, H, PAD = 150, 40, 4
    lo = min(p[1] for p in pts)
    hi = max(p[1] for p in pts)
    if cost > 0:
        lo = min(lo, cost)
        hi = max(hi, cost)
    span = (hi - lo) or 1.0
    step = (W - 2 * PAD) / (len(pts) - 1)

    def _x(i):
        return PAD + i * step

    def _y(v):
        return H - PAD - (v - lo) / span * (H - 2 * PAD)

    path = " ".join(
        ("M" if i == 0 else "L") + f"{_x(i):.1f},{_y(p[1]):.1f}"
        for i, p in enumerate(pts))
    below_cost = cost > 0 and pts[-1][1] < cost
    color = "#DC2626" if below_cost else "#059669"
    parts = [f'<path d="{path}" fill="none" stroke="{color}" stroke-width="1.5" stroke-linejoin="round"/>']
    if cost > 0:
        cy = _y(cost)
        if 0 <= cy <= H:
            parts.append(f'<line x1="{PAD}" y1="{cy:.1f}" x2="{W - PAD}" y2="{cy:.1f}" stroke="#B45309" stroke-width="1" stroke-dasharray="3,3"/>')
            parts.append(f'<text x="{W - PAD}" y="{cy - 2:.1f}" font-size="8" fill="#B45309" text-anchor="end">\u6210\u672c\u00a5{cost:.2f}</text>')
    lx, ly = _x(len(pts) - 1), _y(pts[-1][1])
    parts.append(f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="2" fill="{color}"/>')
    return f'<svg width="{W}" height="{H}" viewBox="0 0 {W} {H}">{"".join(parts)}</svg>'


def render_report_html(report_md, date, grade, total_score):
    """Render markdown report to styled HTML matching analysis template."""
    import re as _re
    lines = report_md.split("\n")
    html_parts = []
    in_table = False

    html_parts.append('<div class="card" style="border-color: rgba(59,130,246,0.5);">')
    html_parts.append('<div class="card-header" style="background: rgba(59,130,246,0.08);">')
    html_parts.append('<span class="card-title">📊 分析报告</span>')
    grade_lower = grade.lower() if grade else "unknown"
    html_parts.append(f'<span class="badge badge-{grade_lower}">{grade}</span>')
    html_parts.append(f'<span style="font-size: 12px; color: var(--text-muted); margin-left: 8px;">日期: {date} | 评分: {total_score}</span>')
    html_parts.append('</div>')
    html_parts.append('<div style="padding: 16px; max-height: 70vh; overflow-y: auto; font-size: 13px; line-height: 1.6; color: var(--text-primary);">')

    def _fmt_bold(text):
        return _re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)

    for line in lines:
        stripped = line.strip()
        if not stripped:
            if in_table:
                html_parts.append('</table>')
                in_table = False
            continue

        if stripped.startswith("---"):
            continue

        if stripped.startswith("# ") and not stripped.startswith("## "):
            if in_table:
                html_parts.append('</table>')
                in_table = False
            text = _fmt_bold(stripped[2:])
            html_parts.append(f'<h2 style="font-size: 18px; font-weight: 700; margin: 16px 0 8px; color: var(--accent); border-bottom: 1px solid var(--border); padding-bottom: 4px;">{text}</h2>')

        elif stripped.startswith("## "):
            if in_table:
                html_parts.append('</table>')
                in_table = False
            text = _fmt_bold(stripped[3:])
            html_parts.append(f'<h3 style="font-size: 15px; font-weight: 600; margin: 14px 0 6px; color: var(--text-primary); padding: 4px 8px; background: rgba(59,130,246,0.05); border-radius: 4px;">{text}</h3>')

        elif stripped.startswith("|"):
            if not in_table:
                html_parts.append('<table style="width:100%; border-collapse: collapse; margin: 8px 0; font-size: 12px;">')
                in_table = True
            cells = stripped.split("|")
            cells = [c for c in cells if c.strip()]
            is_header = all(c.strip().replace("-","").replace(":","") == "" for c in cells)
            if is_header:
                continue
            row_html = "<tr>" + "".join(
                f'<td style="padding: 4px 8px; border-bottom: 1px solid var(--border);">{_fmt_bold(c.strip())}</td>'
                for c in cells
            ) + "</tr>"
            html_parts.append(row_html)

        elif stripped.startswith("- "):
            if in_table:
                html_parts.append('</table>')
                in_table = False
            text = _fmt_bold(stripped[2:])
            html_parts.append(f'<div style="margin: 4px 0 4px 16px; display: flex; gap: 6px;"><span style="color: var(--accent);">•</span><span>{text}</span></div>')

        elif stripped.startswith("> "):
            if in_table:
                html_parts.append('</table>')
                in_table = False
            text = _fmt_bold(stripped[2:])
            html_parts.append(f'<div style="margin: 8px 0; padding: 8px 12px; background: rgba(245,158,11,0.1); border-left: 3px solid #f59e0b; font-size: 12px; border-radius: 0 4px 4px 0;">{text}</div>')

        else:
            if in_table:
                html_parts.append('</table>')
                in_table = False
            text = _fmt_bold(stripped)
            html_parts.append(f'<div style="margin: 4px 0;">{text}</div>')

    if in_table:
        html_parts.append('</table>')
    html_parts.append("</div>")
    html_parts.append("</div>")
    return "\n".join(html_parts)


def render_discover_html(results, market_th=50):
    """Render discover results with valuation columns, add-to-watchlist, and heatmap."""
    # 2026-08-09：已在自选的品渲染「已自选」禁用态，其余渲染「➕ 加入自选」
    _wl_names = set()
    try:
        _conn_wl = db.get_conn()
        try:
            for _rw in _conn_wl.execute("SELECT name FROM items WHERE in_watchlist=1"):
                _wl_names.add(_rw["name"])
        finally:
            _conn_wl.close()
    except Exception:
        pass
    sorted_r = sorted(results, key=lambda r: -(r.get("composite", 0) or r.get("score", 0) or 0))
    top10 = sorted_r[:10]
    errors = [r for r in sorted_r if r.get("error")]
    ok_count = len(sorted_r) - len(errors)

    # ---- Heatmap: by weapon type ----
    from collections import defaultdict
    by_type = defaultdict(list)
    for r in sorted_r:
        if r.get("error"):
            continue
        wt = r["name"].split(" |")[0] if "|" in r["name"] else "other"
        by_type[wt].append(r)

    heatmap_rows = []
    for wt, items in sorted(by_type.items(), key=lambda x: -len(x[1])):
        if len(items) == 0:
            continue
        avg_score = sum(it.get("score", 0) for it in items) / len(items)
        avg_pct = sum(it.get("percentile_90d", 50) for it in items) / len(items)
        best = max(items, key=lambda x: x.get("composite", 0) or x.get("score", 0))
        pct_cls = "green" if avg_pct <= 25 else ("yellow" if avg_pct <= 50 else "red")
        heatmap_rows.append(
            f'<tr><td><strong>{wt}</strong></td>'
            f'<td>{len(items)}</td>'
            f'<td style="color:var(--green);">{avg_score:.1f}</td>'
            f'<td class="{pct_cls}">{avg_pct:.0f}%</td>'
            f'<td style="font-size:12px;">{best["name"][:30]}</td>'
            f'<td style="font-weight:600;">{best.get("composite", best.get("score",0)):.1f}</td></tr>'
        )
    heatmap_html = (
        '<div class="card" style="margin-bottom:16px;">'
        '<div class="card-header"><span class="card-title">\U0001f4ca \u54c1\u7c7b\u70ed\u529b\u56fe</span></div>'
        '<table style="width:100%;font-size:13px;">'
        '<thead><tr><th>\u6b66\u5668</th><th>\u6570\u91cf</th><th>\u5747\u5206</th><th>\u5747\u4f30\u503c</th><th>\u6700\u4f18\u54c1</th><th>\u7efc\u5408</th></tr></thead>'
        '<tbody>' + "".join(heatmap_rows) + '</tbody></table></div>'
    ) if len(by_type) >= 2 else ""

    # ---- Top 10 Table ----
    market_note = ""
    if market_th < 55:
        market_note = ' <span style="font-size:12px;color:var(--yellow);">(\u5927\u76d8TH=' + str(market_th) + ' \u504f\u5f31\uff0c\u4ec5\u5c55\u793a\u9ad8\u5206\u4f4e\u4f30\u54c1)</span>'

    lines = [
        f'<div class="card"><div class="card-header"><span class="card-title">\U0001f50d Top 10 \u9ad8\u5206\u9970\u54c1</span>'
        f'<span class="card-subtitle">\u5df2\u626b\u63cf {ok_count} \u4e2a\u9970\u54c1\uff0c\u5c55\u793a\u524d10{market_note}'
        f' <button class="btn btn-sm btn-outline" onclick="refreshDiscover()" style="margin-left:8px;">\U0001f504 \u5237\u65b0</button></span></div>'
        f'<div class="card-body" style="padding:0;"><div class="table-wrap"><table class="data-table" style="width:100%;">'
        f'<thead><tr><th>#</th><th>\u8bc4\u7ea7</th><th>\u540d\u79f0</th><th>\u4ef7\u683c</th><th>\u8bc4\u5206</th><th>\u7efc\u5408</th><th>%\u4f4d</th><th>\u5468\u671f</th><th>\u64cd\u4f5c</th></tr></thead><tbody>'
    ]
    for idx, r in enumerate(top10):
        if r.get("error"):
            lines.append(f'<tr><td colspan="9" style="color:var(--danger);padding:12px 16px;">{r["name"]}: {r["error"]}</td></tr>')
            continue
        g = r.get("grade", "Z")
        grade_cls = {"S":"grade-s","A":"grade-a","B":"grade-b","C":"grade-c"}.get(g, "grade-z")
        cp = r.get("cycle_label", "") or r.get("cycle_phase", "")
        pct = r.get("percentile_90d", 50)
        pct_clr = "green" if pct <= 25 else ("yellow" if pct <= 50 else "red")
        comp = r.get("composite", 0) or r.get("score", 0)
        rank_style = "font-weight:800;font-size:16px;" + ("color:#ffd700;" if idx == 0 else "color:var(--text-muted);")
        esc_name = r["name"].replace("'", "\\'").replace('"', '&quot;')
        _btn_html = ('<button class="btn btn-xs btn-outline" disabled style="opacity:.55;cursor:default;" title="已在自选">✓ 已自选</button>'
                     if r["name"] in _wl_names else
                     '<button class="btn btn-xs btn-outline" onclick="addToWatchlist(\'' + esc_name + '\', this)" title="加入自选">➕ 加入自选</button>')
        _refresh_btn = ('<button class="btn btn-xs btn-outline" onclick="refreshDiscoverItem(\'' + esc_name + '\', this)" '
                        'title="强制联网重采此品并重算评分">⚡ 刷新</button>')
        lines.append(
            f'<tr><td style="{rank_style}">{idx+1}</td>'
            f'<td><span class="{grade_cls}">{g}</span></td>'
            f'<td style="max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;"><a href="javascript:void(0)" onclick="showDiscoverReport(\'{esc_name}\')" style="color:var(--accent);text-decoration:none;cursor:pointer;" title="\u67e5\u770b\u5206\u6790\u62a5\u544a">{r["name"]}</a></td>'
            f'<td>\u00a5{r.get("price_rmb",0):.2f}</td>'
            f'<td>{r.get("score",0):.1f}</td>'
            f'<td style="font-weight:600;">{comp:.1f}</td>'
            f'<td class="{pct_clr}">{pct:.0f}%</td>'
            f'<td style="font-size:12px;">{cp}</td>'
            f'<td style="white-space:nowrap;">{_btn_html} {_refresh_btn}</td></tr>'
        )
    lines.append("</tbody></table></div></div></div>")
    return heatmap_html + "\n".join(lines)
