# Style Sheet — DIONIX AI Design System

Reference UI: https://www.dionix.ai/ (extracted from live HTML + compiled Tailwind v4 CSS, Aug 2026).
Groundwork runs the exact same stack (Next.js App Router + Tailwind v4), so every recipe below drops in verbatim.

## Design Philosophy (the "feel")

- **Monochrome-first.** The palette is black/white + opacity. Color is used *sparingly* — one animated green pulse dot, one accent color per data-visualization mockup. Reserve saturated color for meaning (live dots, gains, brand logos).
- **Texture over color.** Sections are differentiated by 1px grid hairlines, hairline borders, soft radial glows, and section alternation — not by colored backgrounds.
- **Industrial engineering aesthetic.** Display font (Jura) for headings/numbers, clean grotesque (Puritan) for body. Uppercase micro-labels with wide tracking everywhere. Numerals in big bold Jura.
- **Every surface has a `dark:` twin.** Full class-based dark mode (`dark` class on `<html>`, defaults to system preference). Nothing is styled for one mode only.
- **Micro-interactions everywhere:** hover scale `1.02` / active `0.98`, arrow icons translate on hover, cards lift shadow on hover, staggered scroll-reveal via IntersectionObserver (`opacity:0; transform:translateY(20px)` initial state).

## Fonts

| Role | Family | Weights | Notes |
|---|---|---|---|
| Display / headings / numbers / logo | **Jura** | 300–700 (variable) | `font-jura`, `tracking-tighter` |
| Body / forms / quotes / footer | **Puritan** | 400, 700 | `font-puritan`, quotes rendered `italic` |
| Browser URL bars (mockups) | mono | — | `font-mono` |

Dionix self-hosts via `next/font` (Jura + Puritan are both on Google Fonts — use `next/font/google` for the same look). Utility classes in Tailwind v4:

```css
@theme inline {
  --font-jura: var(--font-jura-src);    /* or your loaded variable */
  --font-puritan: var(--font-puritan-src);
}
```

Mapping for Groundwork: swap Geist → `Jura` (headings/numbers) + `Puritan` (body). This is the single biggest identity change.

## Color System

### Surfaces (monochrome)

- **Light:** `bg-white text-black` · hairline `border-black/10`
- **Dark:** `bg-black text-white` · hairline `border-white/10`
- **Section alternation:** solid ↔ `bg-black/[0.02] dark:bg-white/[0.02]` with `border-y border-black/10 dark:border-white/10`

### Text opacity ladder (systematic)

Body copy = `text-black/60 dark:text-white/60`. Headings = full `text-black dark:text-white`. Meta = `/35`. Labels/eyebrows = `/40`–`/45`. Faint secondary heading line = `/20`–`/45`. Selection: `selection:bg-black selection:text-white dark:selection:bg-white dark:selection:text-black`.

### Accent palette (use sparingly)

- **Emerald** = the one brand accent: `bg-emerald-500` (live dot), `bg-emerald-400` (icon chip), `text-emerald-300` (gains), `from-emerald-600 to-emerald-900` (finance mockup).
- Rose/pink/violet/blue/orange only inside product mockups (fitness = `from-rose-500 to-red-800`, social = `from-violet-600 to-purple-900`, activity chips, avatar gradients).
- Tech-badge brand colors set per-badge via inline `style="--brand:#61DAFB"` consumed by `group-hover/badge:[color:var(--brand)]`.

### The signature background textures

1. **Grid hairlines** (the signature): `bg-[linear-gradient(to_right,#80808008_1px,transparent_1px),linear-gradient(to_bottom,#80808008_1px,transparent_1px)] bg-[size:24px_24px]`. Sizes vary: 24px hero/footer, 32px marquee, 56px portfolio, 64px services/testimonials.
2. **Soft radial orb:** `bg-black/5 dark:bg-white/5 rounded-full blur-[120px]` (900×600 in hero), or `blur-[90px]`.
3. **Radial top glow:** `bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-black/5 via-transparent to-transparent dark:from-white/5`.
4. **Giant watermark wordmark:** `text-black/[0.08] dark:text-white/[0.06]`, up to `text-[16vw]`, in footer/portfolio.

Every decorative layer is `pointer-events-none absolute inset-0` **behind** `container relative z-10`. Every section is `relative overflow-hidden`.

## Typography Conventions

- Headings: `font-jura font-bold tracking-tighter leading-[1.05]`.
  - Hero: `text-4xl sm:text-5xl md:text-7xl lg:text-[5.0rem] xl:text-[5.5rem]`.
  - Section H2: `text-4xl md:text-5xl lg:text-6xl`. Bigger variants: `sm:text-5xl lg:text-7xl`.
- **Eyebrow pill** (every section header): `inline-flex items-center gap-2 px-3 py-1 rounded-full bg-black/5 dark:bg-white/5 border border-black/10 dark:border-white/10 text-sm font-bold uppercase tracking-widest` with a live dot: `<span class="h-2 w-2 rounded-full bg-emerald-500 animate-pulse"></span>`.
- Micro-labels: `text-[10px] font-bold uppercase tracking-widest`; marquee label uses `tracking-[0.28em]`.
- Body: `font-puritan text-lg text-black/60 dark:text-white/60 leading-relaxed max-w-xl mx-auto`.
- Gradient text (hero + select headings only): `text-transparent bg-clip-text bg-gradient-to-r from-black to-black/40 dark:from-white dark:to-white/40`.

## Layout & Spacing

- **Container:** `container mx-auto px-6 md:px-12` everywhere.
- **Section rhythm:** `py-24 md:py-32`; CTA `pt-32 pb-20 sm:pt-36 sm:pb-24`; hero `min-h-screen pt-24 pb-12`.
- Section header block: `text-center max-w-3xl mx-auto mb-16` (trio: eyebrow pill → H2 → body paragraph).
- Standard padding unit scale = Tailwind `--spacing: .25rem`.

## Radius / Borders / Shadows

| Token | Value |
|---|---|
| `rounded-lg` | chips, buttons, inputs |
| `rounded-xl` | list rows, cards, filter pills, in-phone screens |
| `rounded-2xl` | big cards (portfolio preview, testimonial cards, list panel) |
| `rounded-[32px]` / `rounded-[40px]` | phone mockup bezels |
| `rounded-full` | pills, buttons, avatars, dots, socials |
| Hairline border | `border-black/10 dark:border-white/10` (universal default) |
| Section divider | `border-y border-black/10 dark:border-white/10` |
| Cards | `shadow-lg ring-1 ring-black/10 hover:shadow-2xl` or `shadow-xl shadow-black/[0.04] backdrop-blur-sm` |
| Phone glow | `shadow-[0_0_60px_rgba(0,0,0,0.3)]` |

## Buttons

**Primary / CTA:** `font-bold text-sm uppercase tracking-widest rounded-lg bg-black text-white dark:bg-white dark:text-black`, with a white sweep on hover (`absolute inset-0 bg-white/20 translate-y-full group-hover:translate-y-0 transition-transform duration-300 ease-in-out`) + arrow icon `group-hover:translate-x-1`. Sizes: `px-6 py-2.5` (navbar) to `px-8 py-4` (hero/CTA).

**Secondary / outline:** `border border-black/15 dark:border-white/15 hover:bg-black/5 dark:hover:bg-white/5`, same text recipe.

**Micro CTA:** `inline-flex items-center gap-2 rounded-xl bg-black px-6 text-xs font-bold uppercase tracking-widest ... hover:scale-[1.02] active:scale-[0.98]`.

**Icon round button:** `grid h-9 w-9 place-items-center rounded-full border border-black/10 bg-white text-black hover:border-black hover:bg-black hover:text-white`.

## Component Recipes

### Navbar
`header fixed top-0 w-full z-[100] transition-all duration-300 border-b bg-transparent py-6` → `container flex items-center justify-between`. Logo: `font-jura font-bold text-2xl tracking-tighter`. Links: `text-sm font-bold uppercase tracking-widest text-black/70 hover:text-black`. Mobile: full-screen `fixed inset-0 z-[99] bg-white dark:bg-black` panel with icon chips (`h-10 w-10 rounded-lg bg-black/5`), links `text-base font-bold uppercase tracking-widest`, CTA `block w-full rounded-lg bg-black px-6 py-3.5`. Hamburger = 3 × `h-[2px] w-5 rounded-full bg-current` bars.

### Section header trio (reuse everywhere)
```html
<div class="text-center max-w-3xl mx-auto mb-16">
  <div class="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-black/5 dark:bg-white/5 border border-black/10 dark:border-white/10 text-sm font-bold uppercase tracking-widest mb-6">
    <span class="h-2 w-2 rounded-full bg-emerald-500 animate-pulse"></span>What We Build
  </div>
  <h2 class="font-jura text-4xl md:text-5xl lg:text-6xl font-bold tracking-tighter mb-6">FIRST LINE<br>
    <span class="text-black/20 dark:text-white/20">SECOND LINE</span>
  </h2>
  <p class="text-lg text-black/60 dark:text-white/60 font-puritan max-w-xl mx-auto leading-relaxed">...</p>
</div>
```

### Tech marquee (seamless loop)
`flex w-max animate-[logo-scroll-left_48s_linear_infinite]` track containing **two identical** `<ul>`s; pause on hover: `group-hover:[animation-play-state:paused] motion-reduce:[animation-play-state:paused]`. Edge fades: `absolute inset-y-0 left-0 w-16 bg-gradient-to-r from-white to-transparent dark:from-black`. Badges: `flex h-11 items-center gap-2.5 rounded-full border border-black/[0.07] bg-white/60 px-4 backdrop-blur-sm hover:-translate-y-0.5 hover:shadow-md` with inline `--brand`.

### Portfolio list + browser preview
List column: `rounded-2xl border border-black/10 bg-white/70 p-2 shadow-xl shadow-black/[0.04] backdrop-blur-sm`; active row has `border-black/20 bg-black/[0.04]` + left rail `absolute inset-y-2.5 left-0 w-1 rounded-full bg-gradient-to-b from-neutral-400 to-neutral-600`. Preview: `rounded-2xl border shadow-2xl shadow-black/10` with browser chrome (traffic dots `h-3 w-3 rounded-full bg-red-400/80` + URL pill `font-mono text-[10px]`), overlay caption `bg-gradient-to-t from-black/70 via-black/10 to-transparent`. Tech chips: `rounded-lg border border-black/10 bg-black/[0.03] px-3 py-1.5 text-[10px] font-bold uppercase tracking-widest text-black/55`.

### Testimonial cards
`rounded-2xl bg-black/[0.03] dark:bg-white/[0.03] shadow-lg ring-1 ring-black/10 hover:shadow-2xl`, portrait video thumb with `bg-gradient-to-b from-black/30 via-transparent to-black/60`, frosted play button (`h-16 w-16 rounded-full border border-white/30 bg-white/20 backdrop-blur-md group-hover:scale-110`), italic Puritan quote, `font-jura` name, `text-[9px] uppercase tracking-widest` role.

### Phone mockup
`rounded-[40px] bg-black border-[6px] border-neutral-800 shadow-[0_0_60px_rgba(0,0,0,0.3)]` + notch (`w-[100px] h-[26px] bg-black rounded-b-2xl`) + status bar `text-[10px] font-semibold`. Side phones: `-rotate-6 opacity-30 border-[5px] rounded-[32px]` (hidden below lg).

### Forms / inputs (contact page)
`h-12 w-full rounded-xl border border-black/10 bg-black/[0.02] pl-11 pr-4 font-puritan text-sm focus:border-black/40 focus:bg-white dark:focus:bg-white dark:focus:text-black`. Inputs never get heavy borders — hairline until focus.

### Footer
`border-t border-black/10 pt-20 sm:pt-32`, grid `lg:grid-cols-12` (col 5 brand + col 7 link columns), link headings `font-jura text-sm uppercase tracking-widest border-l-2 border-black pl-3`, links `text-sm text-black/60 hover:translate-x-1`, socials `w-10 h-10 rounded-full bg-black/5 border border-black/10 hover:bg-black hover:text-white`, giant watermark wordmark, `border-t border-black/[0.05]` copyright bar, back-to-top pill.

### Floating badge
`fixed bottom-6 right-6 z-50` pill `rounded-2xl bg-black text-white shadow-[0_8px_40px_rgba(0,0,0,0.35)]` + `animate-ping` emerald dot.

## Animations

- `logo-scroll-left/right` keyframes translate `0 → -50%` (marquee, `48s linear infinite`).
- `dx-gentle-float` (6s ease-in-out, ±5px), `dx-orb-blue` (7s), `dx-orb-violet` (5s) — hero orbs/mockup. All respect `prefers-reduced-motion`.
- Stock `animate-pulse` (live dots), `animate-ping` (floating badge).
- Default transition `transition-all duration-300`; `duration-500/700` for image crossfade, shadow, zoom.
- Scroll-reveal: SSR initial `style="opacity:0;transform:translateY(20px)"`, client IntersectionObserver flips visible (staggered `transition-delay`).

## Applying This to Groundwork (dashboard app)

The dashboard is already Next 16 + Tailwind v4 — the same stack. Recommended order:

1. **Fonts:** `layout.tsx` — replace `Geist/Geist_Mono` with `Jura` (variable, headings/numbers) + `Puritan` (body). Body tag gets `font-puritan`.
2. **Theme:** `globals.css` — replace the Uber palette with the monochrome system. Keep a single brand accent (suggest emerald `#10b981` = `emerald-500` for "live/active" indicators and the brand dot). Add `--font-jura` / `--font-puritan` to `@theme inline`.
3. **Surfaces:** `bg-white text-black dark:bg-black dark:text-white`, section alternation, hairline borders, grid-hairline + orb texture on the marketing-ish pages (login, signup).
4. **Components:** swap header to the transparent-fixed navbar recipe; use the eyebrow-pill + H2 trio for page titles; Jura for all stats/numbers; uppercase `tracking-widest` micro-labels for form labels and section tags; hairline rounded-xl inputs; primary buttons = solid black (or white in dark) with sweep hover.
5. **Dark mode:** ensure every class has its `dark:` twin and wire the class-toggle (dionix uses a `<html class="dark">` + localStorage/system script).
6. **Accent discipline:** emerald pulse dot only for live/positive indicators; keep status colors (e.g. SUPPORTED/EMBELLISHED/FABRICATED, score bands) mapped to muted hues on the black/white canvas rather than loud fills.

**Do NOT copy:** dionix's phone mockups, portfolio browser-preview pattern, or giant watermark wordmarks into a data-heavy dashboard — those are marketing-page motifs. Steal the tokens, type scale, buttons, cards, hairline/glow texture system, and section-header trio.
