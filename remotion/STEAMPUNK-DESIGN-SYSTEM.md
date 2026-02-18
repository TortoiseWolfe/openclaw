# Steampunk Design System

Victorian industrial aesthetic. Brass, verdigris, gaslight, aged parchment.
Both brands are **dark themes** with warm atmospheric radial gradients.

---

## Brands

### ScriptHammer — "Brass Workshop"
Warm-toned. Polished brass, dark mahogany, gaslight amber.
Like a Victorian inventor's forge where code is hammered into shape.

### TurtleWolfe — "Patina & Verdigris"
Cool-toned. Oxidized bronze with green patina accents.
Like an alchemist's workshop where copper instruments have aged beautifully.

---

## Color Palettes

### ScriptHammer

| Token       | Hex         | Usage                              |
|-------------|-------------|------------------------------------|
| bg          | `#1a1410`   | Page/canvas background             |
| bgCard      | `#2a2218`   | Card/panel surfaces                |
| accent      | `#c8883c`   | Primary brass accent, links, CTAs  |
| accentDim   | `#a06a28`   | Hover/pressed states, borders      |
| text        | `#ede0c8`   | Primary body text (aged parchment) |
| textMuted   | `#8a7a5a`   | Secondary text, captions, labels   |
| codeGreen   | `#dcc89a`   | Code syntax highlight (strings)    |
| codeBlue    | `#3a4850`   | Code block side-accent bar         |
| codeBg      | `#141010`   | Code block background              |
| overlay     | `rgba(26, 20, 16, 0.88)` | Modal/overlay backdrop  |

### TurtleWolfe

| Token       | Hex         | Usage                              |
|-------------|-------------|------------------------------------|
| bg          | `#0c1210`   | Page/canvas background             |
| bgCard      | `#162320`   | Card/panel surfaces                |
| accent      | `#5ab88a`   | Primary verdigris accent           |
| accentDim   | `#3d8a65`   | Hover/pressed states, borders      |
| text        | `#e8dcc8`   | Primary body text (aged parchment) |
| textMuted   | `#8a7a60`   | Secondary text, captions, labels   |
| codeGreen   | `#7eeaae`   | Code syntax highlight (strings)    |
| codeBlue    | `#5a4a3a`   | Code block side-accent bar         |
| codeBg      | `#0a100d`   | Code block background              |
| overlay     | `rgba(12, 18, 16, 0.88)` | Modal/overlay backdrop  |

---

## Typography

Both brands use the same font stack. The serif heading font gives a Victorian
feel; the monospace display font adds an industrial/technical edge.

| Role     | Font Stack                                       | Usage                    |
|----------|--------------------------------------------------|--------------------------|
| heading  | `'Liberation Serif', Georgia, serif`             | Titles, headings, cards  |
| mono     | `'Liberation Mono', 'Courier New', monospace`    | Code blocks, terminals   |
| display  | `'Liberation Mono', 'Courier New', monospace`    | Taglines, accent text    |

**Web-safe equivalents** (when Liberation fonts aren't available):
- Heading: `Georgia, 'Times New Roman', serif`
- Mono/Display: `'Courier New', Courier, monospace`

**Google Fonts alternatives** (if using web fonts):
- Heading: `Playfair Display`, `Lora`, or `Crimson Text`
- Display: `Space Mono`, `JetBrains Mono`, or `Fira Code`

---

## Effects

### ScriptHammer

| Effect            | CSS Value                                                                    |
|-------------------|------------------------------------------------------------------------------|
| bgGradient        | `radial-gradient(ellipse at 25% 35%, #2e2418 0%, #1a1410 65%)`              |
| accentGlow        | `box-shadow: 0 0 28px rgba(200, 136, 60, 0.22)`                             |
| accentTextShadow  | `text-shadow: 0 0 48px rgba(200, 136, 60, 0.3)`                             |
| cardShadow        | `box-shadow: 0 4px 24px rgba(0,0,0,0.5), inset 0 1px 0 rgba(200,136,60,0.08)` |
| codeBorderGlow    | `box-shadow: 0 0 14px rgba(200, 136, 60, 0.1)`                              |

### TurtleWolfe

| Effect            | CSS Value                                                                    |
|-------------------|------------------------------------------------------------------------------|
| bgGradient        | `radial-gradient(ellipse at 25% 35%, #1a3028 0%, #0c1210 65%)`              |
| accentGlow        | `box-shadow: 0 0 28px rgba(90, 184, 138, 0.22)`                             |
| accentTextShadow  | `text-shadow: 0 0 48px rgba(90, 184, 138, 0.28)`                            |
| cardShadow        | `box-shadow: 0 4px 24px rgba(0,0,0,0.5), inset 0 1px 0 rgba(90,184,138,0.08)` |
| codeBorderGlow    | `box-shadow: 0 0 14px rgba(126, 234, 174, 0.12)`                            |

---

## Design Patterns

### Backgrounds
- Never flat solid colors. Always use the `bgGradient` radial gradient.
- Gradient focal point is offset upper-left (`25% 35%`) to create atmospheric depth.
- Cards use `bgCard` with the `cardShadow` (outer shadow + subtle inset highlight).

### Accent Usage
- `accent` for primary interactive elements: links, buttons, active indicators.
- `accentDim` for hover/focus states and decorative borders.
- `accentGlow` box-shadow on focused or highlighted elements.
- `accentTextShadow` on hero titles and emphasized headings.

### Decorative Elements
- **Corner brackets**: L-shaped border segments at card corners (2px width, accent color, 0.25 opacity). Evokes brass plate corners on Victorian equipment.
- **Accent bars**: 4px left border on code blocks and callouts using `accent` color with `codeBorderGlow`.
- **Dividers**: 1px horizontal rules using `accentDim` at ~30% opacity.

### Code Blocks
- Background: `codeBg` (near-black, slightly warm/cool-shifted per brand).
- Left accent bar: 4px solid `accent` with `codeBorderGlow`.
- Text: `codeGreen` for strings/keywords, `text` for identifiers.
- Font: `mono` stack, slightly smaller than body text.
- Corner radius: 8px (subtle, not overly rounded).

### Cards & Panels
- Background: `bgCard`.
- Shadow: `cardShadow` (combines depth shadow with thin inset highlight).
- Border: none (shadow provides separation) or 1px `accentDim` at 15% opacity.
- Corner radius: 12px for major cards, 8px for smaller elements.

### Text Hierarchy
- H1/Hero: `heading` font, `text` color, `accentTextShadow`, 64-80px.
- H2/Section: `heading` font, `text` color, 36-48px.
- Body: `heading` font, `text` color, 24-28px.
- Muted/Label: `heading` font, `textMuted` color, 18-22px.
- Code/Display: `mono`/`display` font, `codeGreen` or `accent`, 18-24px.

---

## CSS Custom Properties (Copy-Paste Ready)

### ScriptHammer
```css
:root {
  --color-bg: #1a1410;
  --color-bg-card: #2a2218;
  --color-accent: #c8883c;
  --color-accent-dim: #a06a28;
  --color-text: #ede0c8;
  --color-text-muted: #8a7a5a;
  --color-code-green: #dcc89a;
  --color-code-blue: #3a4850;
  --color-code-bg: #141010;
  --color-overlay: rgba(26, 20, 16, 0.88);

  --font-heading: 'Liberation Serif', Georgia, serif;
  --font-mono: 'Liberation Mono', 'Courier New', monospace;
  --font-display: 'Liberation Mono', 'Courier New', monospace;

  --bg-gradient: radial-gradient(ellipse at 25% 35%, #2e2418 0%, #1a1410 65%);
  --shadow-accent-glow: 0 0 28px rgba(200, 136, 60, 0.22);
  --shadow-accent-text: 0 0 48px rgba(200, 136, 60, 0.3);
  --shadow-card: 0 4px 24px rgba(0, 0, 0, 0.5), inset 0 1px 0 rgba(200, 136, 60, 0.08);
  --shadow-code-border: 0 0 14px rgba(200, 136, 60, 0.1);
}
```

### TurtleWolfe
```css
:root {
  --color-bg: #0c1210;
  --color-bg-card: #162320;
  --color-accent: #5ab88a;
  --color-accent-dim: #3d8a65;
  --color-text: #e8dcc8;
  --color-text-muted: #8a7a60;
  --color-code-green: #7eeaae;
  --color-code-blue: #5a4a3a;
  --color-code-bg: #0a100d;
  --color-overlay: rgba(12, 18, 16, 0.88);

  --font-heading: 'Liberation Serif', Georgia, serif;
  --font-mono: 'Liberation Mono', 'Courier New', monospace;
  --font-display: 'Liberation Mono', 'Courier New', monospace;

  --bg-gradient: radial-gradient(ellipse at 25% 35%, #1a3028 0%, #0c1210 65%);
  --shadow-accent-glow: 0 0 28px rgba(90, 184, 138, 0.22);
  --shadow-accent-text: 0 0 48px rgba(90, 184, 138, 0.28);
  --shadow-card: 0 4px 24px rgba(0, 0, 0, 0.5), inset 0 1px 0 rgba(90, 184, 138, 0.08);
  --shadow-code-border: 0 0 14px rgba(126, 234, 174, 0.12);
}
```

---

## Tailwind Config (if using Tailwind CSS)

```js
// tailwind.config.js — ScriptHammer brand
module.exports = {
  theme: {
    extend: {
      colors: {
        steam: {
          bg: '#1a1410',
          card: '#2a2218',
          accent: '#c8883c',
          'accent-dim': '#a06a28',
          text: '#ede0c8',
          muted: '#8a7a5a',
          'code-green': '#dcc89a',
          'code-blue': '#3a4850',
          'code-bg': '#141010',
        },
      },
      fontFamily: {
        heading: ["'Liberation Serif'", 'Georgia', 'serif'],
        mono: ["'Liberation Mono'", "'Courier New'", 'monospace'],
      },
      boxShadow: {
        'accent-glow': '0 0 28px rgba(200, 136, 60, 0.22)',
        'card': '0 4px 24px rgba(0,0,0,0.5), inset 0 1px 0 rgba(200,136,60,0.08)',
        'code-glow': '0 0 14px rgba(200, 136, 60, 0.1)',
      },
    },
  },
};
```

---

## Source of Truth

Canonical theme definition: `remotion/src/lib/theme.ts`
