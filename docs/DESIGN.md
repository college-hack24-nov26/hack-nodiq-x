# NODIQ-X Design System

![theme](https://img.shields.io/badge/theme-dark--industrial-FF7A18?style=flat-square&labelColor=101416)
![source](https://img.shields.io/badge/source%20of%20truth-variables.css-3BA5FF?style=flat-square&labelColor=101416)
![status](https://img.shields.io/badge/tokens.css-legacy%2C%20frozen-7E898E?style=flat-square&labelColor=101416)

How NODIQ-X should look and feel. The canonical source of truth is `apps/web/src/styles/variables.css` — this document explains it, that file defines it. Legacy aliases live in `styles/tokens.css` and must not gain new values.

---

## Contents

1. [Style](#1-style)
2. [Colors](#2-colors)
3. [Typography](#3-typography--two-tier-system)
4. [Radius](#4-radius)
5. [Components](#5-components)
6. [Layout](#6-layout)
7. [UX requirements](#7-ux-requirements)

---

## 1. Style

- **Dark-industrial instrument panel** — dark theme is the default; light mode is a first-class mirror via CSS variables.
- Professional, technical, trustworthy. Microscopy software, not a consumer app.
- Motion is purposeful: soft fades, subtle hover lifts, no decoration for its own sake.
- The login experience (video loop, animations) is part of the product identity — preserve it.

---

## 2. Colors

Dark theme (default). Every value below is a CSS variable — **never hardcode hex.**

| Swatch | Token | Value | Use |
|:---:|---|---|---|
| ![](https://img.shields.io/badge/-%20-101416?style=flat-square) | `--color-bg` | `#101416` | App background |
| ![](https://img.shields.io/badge/-%20-1A2226?style=flat-square) | `--color-bg-2` … `--color-bg-6` | `#12191C` → `#212E32` | Depth ladder for sections |
| ![](https://img.shields.io/badge/-%20-1B2226?style=flat-square) | `--color-surface` | `#1B2226` | Cards, panels |
| ![](https://img.shields.io/badge/-%20-252E33?style=flat-square) | `--color-elevated` | `#252E33` | Popovers, modals, raised surfaces |
| ![](https://img.shields.io/badge/-%20-2E383D?style=flat-square) | `--color-border` | `#2E383D` | Default borders |
| ![](https://img.shields.io/badge/-%20-3A454B?style=flat-square) | `--color-border-strong` | `#3A454B` | Emphasized borders, inputs on focus |
| ![](https://img.shields.io/badge/-%20-FF7A18?style=flat-square) | `--color-primary` | `#FF7A18` | Brand orange — primary actions, active states |
| ![](https://img.shields.io/badge/-%20-FF922E?style=flat-square) | `--color-primary-hover` | `#FF922E` | Primary hover |
| ![](https://img.shields.io/badge/-%20-FF7A18?style=flat-square) | `--color-primary-dim` | `rgba(255,122,24,.12)` | Tinted fills |
| ![](https://img.shields.io/badge/-%20-FF7A18?style=flat-square) | `--color-primary-ring` | `rgba(255,122,24,.35)` | Focus rings |
| ![](https://img.shields.io/badge/-%20-E8ECEE?style=flat-square) | `--color-text` | `#E8ECEE` | Primary text |
| ![](https://img.shields.io/badge/-%20-9AA6AC?style=flat-square) | `--color-text-secondary` | `#9AA6AC` | Secondary text |
| ![](https://img.shields.io/badge/-%20-7E898E?style=flat-square) | `--color-text-tertiary` | `#7E898E` | Metadata, labels (readability floor) |
| ![](https://img.shields.io/badge/-%20-39C27F?style=flat-square) | `--color-success` | `#39C27F` | Pass, approved, healthy |
| ![](https://img.shields.io/badge/-%20-F2B84B?style=flat-square) | `--color-warning` | `#F2B84B` | Review needed, caution |
| ![](https://img.shields.io/badge/-%20-EF5350?style=flat-square) | `--color-error` | `#EF5350` | Failing, destructive, rejected |
| ![](https://img.shields.io/badge/-%20-3BA5FF?style=flat-square) | `--color-info` | `#3BA5FF` | Informational accents |
| ![](https://img.shields.io/badge/-%20-4FD1C5?style=flat-square) | `--accent-cyan` | `#4FD1C5` | **Chart secondary series only** — never for UI chrome |

Light mode redefines the same variables; components must never assume dark values.

---

## 3. Typography — Two-Tier System

The split is **content type**, never page type.

| Variable | Typeface | Used for | Share |
|---|---|---|:---:|
| `--font-ui` | Inter | Headings, nav, buttons, forms, cards, descriptions, landing copy | ~80–90% |
| `--font-tech` | IBM Plex Mono | The instrument layer: analysis IDs, measurements, percentages, resolution, engine versions, ISO/JIS labels | ~10–20% |

Semantic aliases: `--font-display` / `--font-body` → Inter, `--font-mono` → IBM Plex Mono.

**Type scale (px)** — canonical ladder from `variables.css`; pick the nearest step instead of inventing sizes:

`micro 10 · label 12 · body 16 · title 22 · display-sm 36`

---

## 4. Radius

Canonical 4/8/12 scale only.

| Token | Value | Use |
|---|:---:|---|
| `--radius-sm` | `4px` | Inputs, chips, small controls |
| `--radius-md` | `8px` | Buttons, table cells, inner panels |
| `--radius-lg` | `12px` | Cards, modals, popovers |

---

## 5. Components

| Component | Spec |
|---|---|
| **Buttons** | Primary (orange fill, dark text), secondary (elevated surface + border), destructive (error color). Focus shows the primary ring; disabled reduces opacity and drops pointer events. |
| **Cards** | `--color-surface`, `--radius-lg`, `--color-border`, hover lift allowed. |
| **Tables** | Uppercase mono headers on elevated background, striped rows, hover highlight, horizontally scrollable wrapper (popovers escape it — fixed layers). |
| **Charts** | Primary series brand orange, secondary series cyan, dashed gridlines, labeled axes, mean/reference markers, per-point value labels. |
| **Status** | Success/warning/error dot + label; verdicts (`PASS` / `REVIEW` / `FAIL`) use mono, bordered chips. |

**Status chip reference**

![PASS](https://img.shields.io/badge/PASS-39C27F?style=flat-square&labelColor=101416) ![REVIEW](https://img.shields.io/badge/REVIEW-F2B84B?style=flat-square&labelColor=101416) ![FAIL](https://img.shields.io/badge/FAIL-EF5350?style=flat-square&labelColor=101416)

---

## 6. Layout

- Collapsible sidebar: `72px` collapsed / `260px` expanded (`--sidebar-width`, `--sidebar-expanded-width`).
- Content max-width via existing page containers; consistent page padding.

---

## 7. UX requirements

- Mobile responsive down to 375px; test 375 / 768 / 1440.
- Every async surface has **loading**, **empty**, and **error** states.
- Accessible forms: labels, focus rings, error text tied to inputs.
- Keyboard-reachable interactions; outside-click dismissal for menus.
- Tooltips/toasts never block critical actions.

---

*NODIQ-X — Design System. `variables.css` is canonical; `tokens.css` is legacy and frozen.*