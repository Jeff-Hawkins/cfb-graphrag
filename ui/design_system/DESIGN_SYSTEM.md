# CFB Coaching Intelligence Platform — Design System

> **Claude Code must read this file before any UI work in this repo.**
> Palette, role colors, typography, component rules, and vis.js node specs are
> all defined here. All new UI components must conform to these tokens exactly.

---

## Palette

```css
--navy:    #0F1729  /* page background */
--navy2:   #162035  /* subtle bg variant */
--navy3:   #1E2D4A  /* input/control bg */
--navy4:   #253558  /* hover states */
--card:    #182038  /* card surfaces */
--card2:   #1E2A45  /* nested card surfaces */
--accent:  #4F8EF7  /* primary blue — links, active states */
--accent2: #E8503A  /* coral — alerts, OC role */
--green:   #34C97B  /* positive deltas, SP+ highlight */
--text:    #FFFFFF
--text2:   #A8B8D8  /* secondary text */
--text3:   #5C7099  /* muted/labels */
--border:  rgba(255,255,255,0.07)
--border2: rgba(255,255,255,0.12)
```

---

## Role Colors (node styling)

| Role | Background | Border     | Font    | Usage                          |
|------|------------|------------|---------|--------------------------------|
| HC   | `#F5C842`  | `#C49A1A`  | `#0F1729` | Head coaches                 |
| OC   | `#E8503A`  | `#B83020`  | `#FFFFFF` | Offensive coordinators       |
| DC   | `#4F8EF7`  | `#2060C0`  | `#FFFFFF` | Defensive coordinators       |
| POS  | `#A78BFA`  | `#7050CC`  | `#FFFFFF` | Position coaches             |

---

## Typography

| Use              | Font                 | Weights         |
|------------------|----------------------|-----------------|
| Display/headers  | Barlow Condensed     | 700, 800, 900   |
| Body/data        | Inter                | 400, 500, 600   |
| Monospace/labels | IBM Plex Mono        | 400, 500 — optional, Inter acceptable |

Google Fonts URL:
```
https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@700;800;900&family=Inter:wght@400;500;600&display=swap
```

---

## Component Rules

- **Cards**: `background: var(--card)`, `border-radius: 14px`, `border: 1px solid var(--border)`
- **Buttons**: `background: var(--navy3)`, `border-radius: 8px`, hover → `var(--navy4)`
- **Active state**: `background: rgba(79,142,247,0.15)` + `border: rgba(79,142,247,0.4)`
- **Stat cards**: `background: var(--navy3)`, `border-radius: 8px`
- **Dividers**: `1px solid var(--border)`
- **No drop shadows. No gradients (hero background excepted). Flat surfaces only.**
- **Border widths**: 1px standard, 2.5px for root node only

---

## vis.js Node Rules

| Node type               | Shape   | Size | Border width | Notes                       |
|-------------------------|---------|------|--------------|-----------------------------|
| Root node (depth=0)     | `box`   | 32   | 2.5          |                             |
| HC (depth > 0)          | `ellipse` | 22 | 1            |                             |
| OC or DC                | `ellipse` | 17 | 1            |                             |
| Position coaches (POS)  | `ellipse` | 13 | 1            |                             |

### Layout options

```json
{
  "layout": {
    "hierarchical": {
      "enabled": true,
      "direction": "UD",
      "levelSeparation": 95,
      "nodeSpacing": 85,
      "sortMethod": "directed"
    }
  },
  "physics": { "enabled": false }
}
```

### Edge style

```json
{
  "color": { "color": "rgba(168,184,216,0.15)", "highlight": "rgba(168,184,216,0.4)" },
  "width": 1.5,
  "smooth": { "type": "cubicBezier", "forceDirection": "vertical", "roundness": 0.4 }
}
```

### CDN

```
https://cdnjs.cloudflare.com/ajax/libs/vis/4.21.0/vis.min.js
https://cdnjs.cloudflare.com/ajax/libs/vis/4.21.0/vis.min.css
```

---

## Three-Panel Layout (coaching_tree.html)

```
+--------------------+---------------------------+----------------------+
|   Left   200px     |   Center  (flex 1)        |   Right  220px       |
|                    |                           |                      |
| Depth slider 1-4   |   vis.js Network canvas   | Coach detail card    |
| Role filter        |   hierarchical UD         | • Name (Barlow Cond) |
| Preset buttons:    |   physics disabled        | • Role badge         |
|  • Saban           |                           | • Team + Years       |
|  • Meyer           |                           | • SP+ stat card      |
|  • Smart           |                           | • Mentee count       |
+--------------------+---------------------------+ • Explain block      |
                                                  +----------------------+
```

- Total height: 580px
- Preset buttons send `window.parent.postMessage({type:'preset', name:'...'}, '*')`

---

## Phase 4 Migration Path

All tokens in this file migrate directly to the React + D3 rebuild (F11):
- Palette → `:root { --navy: #0F1729; ... }` CSS custom properties
- Role colors → D3 scale or React context
- Component rules → Tailwind config or styled-components theme
- vis.js node/edge schema → D3 data format (near 1:1)
- Three-panel layout → CSS Grid

The Streamlit shell and JSON-inject handoff are the only throwaway pieces (~20 lines).
