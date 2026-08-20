# Design System Master File

> **LOGIC:** 当构建具体页面时，先检查 `design-system/pages/[page-name].md`。
> 若该文件存在，其规则**覆盖**本 Master 文件。
> 若不存在，严格遵循下方规则。

> **2026-08-20 归档（UI-1）**：本文档原为早期深色 OLED 概念稿，与实际系统脱节。
> **实际系统 = `webapp/static/css/style.css` v3 浅色 indigo 设计系统**，是唯一生效的样式事实源。
> 页面实际渲染一律以 `style.css` v3 的 CSS 变量与语义类为准；本文下方历史章节仅供追溯，不再作为实现依据。

---

## 实际设计系统（style.css v3，唯一事实源）

- **主题**：浅色 dashboard（bright white fintech trading dashboard），indigo 主色。
- **字体**：IBM Plex Sans + 中文回退（Microsoft YaHei / PingFang SC / Noto Sans SC）。
- **间距**：4px 间距刻度（`--space-1` 4px ~ `--space-8` 32px）。
- **圆角**：6/10/14px 三级（`--radius-sm` / `--radius` / `--radius-lg`）。
- **触控目标**：移动端 ≥44px（`@media (max-width:639px)`）。
- **可访问性**：skip-link、`:focus-visible` 可见焦点、`prefers-reduced-motion` 尊重、正文对比度 ≥4.5:1。
- **语义色**：`--green` 涨/`--red` 跌（中国股市口径）、`--blue` 信息、`--purple` 紫色、`--amber/--yellow` 警示。
- **emoji**：图标型 emoji（📈📉📊🔍）可作装饰；**禁止 emoji 作为唯一状态载体**——趋势/评级等状态须配文字或 `aria-label`。

### 核心 CSS 变量（节选，完整见 style.css `:root`）

| 角色 | 变量 | 值 |
|---|---|---|
| 主色 | `--accent` | `#4F46E5` |
| 涨 | `--green` | `#059669` |
| 跌 | `--red` | `#DC2626` |
| 信息蓝 | `--blue` | `#2563EB` |
| 警示 | `--yellow` | `#B45309` |
| 正文 | `--text-primary` | `#0F172A` |

---

## 历史章节（追溯用，不再作为实现依据）

<details>
<summary>2026-08-08 早期深色 OLED 概念稿（已废弃）</summary>

**Project:** CS Market
**Generated:** 2026-08-08 09:50:27
**Category:** Financial Dashboard
**Design Dials:** Motion 2/10 (Subtle) | Density 8/10 (Dense / Dashboard)

### Color Palette（废弃）

| Role | Hex | CSS Variable |
|------|-----|--------------|
| Primary | `#1E3A8A` | `--color-primary` |
| On Primary | `#FFFFFF` | `--color-on-primary` |
| Secondary | `#3B82F6` | `--color-secondary` |
| Accent/CTA | `#7C3AED` | `--color-accent` |
| Background | `#F8FAFC` | `--color-background` |
| Foreground | `#1E40AF` | `--color-foreground` |
| Muted | `#E9EEF5` | `--color-muted` |
| Border | `#BFDBFE` | `--color-border` |
| Destructive | `#DC2626` | `--color-destructive` |
| Ring | `#1E3A8A` | `--color-ring` |

**Color Notes:** Knowledge blue + link purple + clean white

### Typography（废弃）

- **Heading Font:** Inter
- **Body Font:** Inter
- **Mood:** dark, cinematic, technical, precision, clean, premium, developer, professional, high-end utility

### Spacing Variables（废弃，已被 4px 刻度替代）

| Token | Value | Usage |
|-------|-------|-------|
| `--space-xs` | `2px` / `0.125rem` | Tight gaps |
| `--space-sm` | `4px` / `0.25rem` | Icon gaps, inline spacing |
| `--space-md` | `8px` / `0.5rem` | Standard padding |
| `--space-lg` | `12px` / `0.75rem` | Section padding |
| `--space-xl` | `16px` / `1rem` | Large gaps |
| `--space-2xl` | `24px` / `1.5rem` | Section margins |
| `--space-3xl` | `32px` / `2rem` | Hero padding |

### Shadow Depths（废弃）

| Level | Value | Usage |
|-------|-------|-------|
| `--shadow-sm` | `0 1px 2px rgba(0,0,0,0.05)` | Subtle lift |
| `--shadow-md` | `0 4px 6px rgba(0,0,0,0.1)` | Cards, buttons |
| `--shadow-lg` | `0 10px 15px rgba(0,0,0,0.1)` | Modals, dropdowns |
| `--shadow-xl` | `0 20px 25px rgba(0,0,0,0.15)` | Hero images, featured cards |

### Component Specs（废弃）

```css
/* Primary Button */
.btn-primary {
  background: #7C3AED;
  color: white;
  padding: 12px 24px;
  border-radius: 8px;
  font-weight: 600;
  transition: all 200ms ease;
  cursor: pointer;
}

/* Secondary Button */
.btn-secondary {
  background: transparent;
  color: #1E3A8A;
  border: 2px solid #1E3A8A;
  padding: 12px 24px;
  border-radius: 8px;
  font-weight: 600;
  transition: all 200ms ease;
  cursor: pointer;
}
```

### Style Guidelines（废弃）

**Style:** Dark Mode (OLED)

**Keywords:** Dark theme, low light, high contrast, deep black, midnight blue, eye-friendly, OLED, night mode, power efficient

**Best For:** Night-mode apps, coding platforms, entertainment, eye-strain prevention, OLED devices, low-light

### Page Pattern（废弃）

**Pattern Name:** Minimal Single Column

- **Conversion Strategy:** Single CTA focus. Large typography. Lots of whitespace. No nav clutter. Mobile-first.

### Motion（废弃）

**Scroll Reveal** (Subtle) — 依赖 GSAP + ScrollTrigger，未在实际系统引入。

</details>

---

## 当前交付清单（UI-1，2026-08-20）

- 页面渲染一律以 `style.css` v3 为准；不要在本文件或任何页面文档中复刻旧深色规则。
- 状态色、间距、圆角、字号均引用 CSS 变量，禁止硬编码 hex / 裸 rgba（除非作为 style.css 变量定义）。
- emoji 不承载唯一语义（见上方「实际设计系统」）。
