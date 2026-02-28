# Design Language Audit — Scene Atlas Frontend

**Date:** 2026-02-25
**Scope:** Gallery header/search, FilterMenuContent, TagManagementDialog, ImageViewer
**Purpose:** Make the implicit design language explicit, flag inconsistencies, suggest improvements
**Future constraint:** A light mode (warm off-white, same amber accent) is planned. All fixes should work toward enabling that via the existing CSS custom property system.

---

## 1. Overall Aesthetic Assessment

**Verdict: Strong and distinctive.** The "dark cartographic / archival" direction is well-executed and genuinely unusual — this doesn't look like generic dark-mode UI. The combination works:

- **Deep navy surfaces** with the dot-grid background evoke graph paper and survey maps
- **Warm parchment text** (`#ede8dc`) avoids the cold blue-white of typical dark themes
- **Amber gold** used as a single, deliberate accent creates clear visual wayfinding
- **Cinzel** display font adds genuine character without feeling gimmicky

The overall effect is an opinionated, quality tool interface — closer to a well-made desktop application than a web app. This is exactly right for the target audience (tabletop RPG enthusiasts who care about craft).

### What elevates it
- The amber top-of-viewport stripe (`body::before`) is a signature detail that unifies every view
- The dot-grid background at 28px is subtle enough to not interfere but visible enough to set mood
- Category-coloured tags avoid the monotony of single-colour tag systems
- The FilterMenuContent's visual grid-type tiles (with SVG previews) are a standout UI element — much better than checkboxes

### Risk areas
- The amber accent is doing a LOT of work: active states, focus rings, decorative rules, primary buttons, tab indicators, count badges, the regenerate-tags button, the top stripe. It's close to the threshold where "used sparingly" stops being accurate
- The gap between "polished 4 components" and "everything else" will be very visible to users — the import flow and some older components will feel jarring in comparison

---

## 2. Colour System

### What's codified and consistent
The CSS custom property system in `index.css` is well-structured. The 5-tier surface hierarchy (background → popover → card → muted → secondary) creates clear depth.

### Issues found

#### 2a. DARK_SURFACE constant duplicates a near-token

Both `FilterMenuContent.tsx:101` and `TagManagementDialog.tsx:18` define:
```ts
const DARK_SURFACE = 'hsl(222 22% 10%)'  // ≈ #131924
```

But the `--popover` CSS token is:
```css
--popover: 220 25% 10%;  // ≈ #121720
```

These differ in hue (222 vs 220) and saturation (22% vs 25%). They're visually indistinguishable, but this is a token discipline problem. **DARK_SURFACE should be `hsl(var(--popover))`** — there shouldn't be a second "dark surface" colour living outside the token system.

**Light mode impact:** This is a blocker. Any raw HSL value that isn't routed through a CSS custom property will remain dark navy when the rest of the UI switches to light mode. Every `DARK_SURFACE` usage becomes a visual bug on day one of light mode.

#### 2b. Raw HSL values scattered through inline styles

TagManagementDialog contains many raw colour values that aren't tokens:

| Location | Raw value | Should be |
|----------|-----------|-----------|
| `TagManagementDialog.tsx:543` textarea bg | `hsla(220, 22%, 9%, 0.8)` | A token or DARK_SURFACE variant |
| `TagManagementDialog.tsx:719` add-value bg | `hsla(222, 20%, 14%, 1)` | `hsl(var(--muted))` or similar |
| `TagManagementDialog.tsx:975` alias input bg | `hsla(220, 22%, 9%, 0.9)` | Same as textarea bg above |
| `TagManagementDialog.tsx:518` delete btn border | `hsla(0, 62%, 57%, 0.2)` | `hsl(var(--destructive) / 0.2)` |

These will drift from the token system as the palette evolves. Every raw HSL should reference a `var(--*)` token.

**Light mode impact:** These are the same class of problem as DARK_SURFACE — hardcoded dark-mode colours that will break in light mode. The fix is the same: route through tokens. Any value that needs to differ between themes *must* be a CSS custom property. This is currently ~15-20 raw HSL values across the two most polished components, so it's worth fixing before the pattern spreads further.

#### 2c. Tag colour system is solid (with a light-mode caveat)

The `tagColors.ts` palette is well-designed. The pattern `bg-*-400/10 / text-*-300 / border-*-400/30` creates consistent depth across 24+ colours. The `dot` variant for solid indicators is a good addition.

**Light mode note:** The current tag colours are tuned for dark backgrounds (`text-*-300` is a light tint, `bg-*-400/10` is barely visible on dark). In light mode, you'll likely need `text-*-700` and `bg-*-100` or similar. The clean approach: make `tagColors.ts` export class strings that Tailwind's `dark:` variant can override, or use CSS custom properties per colour family. This doesn't need to be solved now, but the current architecture (static Tailwind class strings) will need a second set of mappings when light mode arrives. Worth keeping in mind during any tag colour refactors.

---

## 3. Typography

### Font roles — codified and consistent

| Font | Role | Used correctly? |
|------|------|----------------|
| Cinzel (`font-display`) | Titles, headings, category names | Yes — consistent across all 4 components |
| Figtree (`font-sans`) | Body text, labels, controls | Yes — it's the default |
| JetBrains Mono (`font-mono`) | Filenames, dimensions, sizes | Yes — used in ImageViewer metadata |

### Size hierarchy — mostly consistent, some drift

The components converge on a clear size scale:

| Role | Size used | Components |
|------|-----------|------------|
| Page/modal title | `text-2xl font-semibold` (Cinzel) | Gallery, ImageViewer |
| Panel title | `text-[13px] font-medium tracking-[0.06em]` (Cinzel) | FilterMenu, TagManagement |
| Category/detail heading | `text-[17px] font-medium tracking-[0.04em]` (Cinzel) | FilterMenu, TagManagement |
| Body text | `text-sm` / `text-xs` (Figtree) | All |
| Micro label | `text-[11px]` or `text-[11.5px]` (Figtree) | All |
| Metadata | `text-[10px]` (JetBrains Mono or Figtree) | ImageViewer, tags |
| Micro count | `text-[9px]` – `text-[10px]` (Figtree) | Badges, tab counts |

### Issues found

#### 3a. Font weight inconsistency on page-level titles

- Gallery `h1`: `font-display text-2xl font-medium tracking-wide`
- ImageViewer `h2` (image name): `font-display text-2xl font-semibold`
- ImageViewer group name: `font-display text-2xl font-semibold text-muted-foreground`

The Gallery title is `font-medium` while the ImageViewer name is `font-semibold`. These are the same visual tier but different weights. **Recommendation:** Both should be `font-semibold` — Cinzel at `medium` weight can feel thin at `text-2xl`.

#### 3b. Tracking values vary without clear logic

- Panel titles (`text-[13px]`): `tracking-[0.06em]`
- Category headings (`text-[17px]`): `tracking-[0.04em]`
- Gallery page title (`text-2xl`): `tracking-wide` (0.025em)
- Section labels: `tracking-[0.1em]` vs `tracking-[0.18em]` vs `tracking-wider` (see 3c)

Tracking should decrease as size increases (larger text needs less letter-spacing). The current values roughly follow this, but the section label inconsistency undermines it.

#### 3c. Section label pattern has 3 variants (should be 1)

This is a key micro-pattern used everywhere — the tiny uppercase label above a section. It appears in 3 slightly different forms:

| Component | Classes |
|-----------|---------|
| TagManagement (Categories, Editing, Icon, Color, Tag Values) | `text-[9.5px] font-semibold tracking-[0.1em] uppercase text-muted-foreground` |
| FilterMenuContent ("Filter by") | `text-[9.5px] font-medium tracking-[0.18em] uppercase text-muted-foreground` |
| ImageViewer (Subgroup, Type, Grid labels) | `text-[10px] uppercase tracking-wider text-muted-foreground/60` |

Differences: `font-semibold` vs `font-medium` vs (none); `tracking-[0.1em]` vs `tracking-[0.18em]` vs `tracking-wider`; `text-muted-foreground` vs `text-muted-foreground/60`.

**Recommendation:** Standardise as a utility class or component. Suggested standard:
```
text-[9.5px] font-semibold tracking-[0.1em] uppercase text-muted-foreground
```

---

## 4. Common Visual Motifs

### 4a. The amber decorative rule (signature motif)

A short gradient line placed below Cinzel titles, used to "underline" headings. This is a strong brand element that should be codified precisely.

**Current variations:**

| Location | Size | Opacity | Pattern |
|----------|------|---------|---------|
| Gallery page title | `h-[1.5px] w-16` | `from-primary/70` | Thicker, wider, dimmer |
| FilterMenuContent panel header | `h-px w-7` | `from-primary` | Thinner, shorter, full |
| TagManagement dialog header | `h-px w-7` | `from-primary` | Thinner, shorter, full |
| FilterMenuContent category detail | `h-px w-6` | `from-primary/60` | Thinner, shortest, dimmer |

FilterMenuContent and TagManagement are consistent with each other at the panel level. The Gallery page uses a different variant. The "Filter by" sub-heading uses yet another.

**Recommendation:** Define two tiers:
- **Page-level rule** (Gallery title): `h-[1.5px] w-16 bg-gradient-to-r from-primary/70 to-transparent`
- **Panel-level rule** (dialogs, popovers): `h-px w-7 bg-gradient-to-r from-primary to-transparent`

Drop the third `w-6 from-primary/60` variant — use the panel-level one for sub-headings too.

### 4b. Left border active indicator

A 2px left border that indicates selection in vertical navigation lists. Used in:
- FilterMenuContent category nav (coloured by tag category)
- FilterMenuContent author checklist (primary for include, destructive for exclude)
- TagManagement category list (coloured by tag category via `border-current`)

This is a strong, consistent pattern. The only difference is TagManagement uses `border-current` (inheriting from the `text-*` colour) while FilterMenuContent uses explicit colour classes. Both produce the same visual result.

### 4c. Dot-grid background

Used in two locations:
- `body` background: 28px grid, `foreground` at 4% opacity
- ImageViewer canvas: 24px grid, white at 4.5% opacity

The different grid sizes and base colours are intentional (body uses parchment dots, canvas uses white dots on a darker surface). This works well — the canvas feels like its own space.

### 4d. The amber top stripe

Split across ImageViewer canvas and sidebar, meeting at the join. This is well-documented in `visual-language.md` and implemented consistently.

---

## 5. Standardised Elements

### 5a. Input fields — 4 different implementations (problem)

This is the most significant inconsistency across the 4 components. There are effectively 4 input styles in use:

| Variant | Height | Size | Background | Focus | Used in |
|---------|--------|------|------------|-------|---------|
| **Formal `<Input>`** | `h-10` | `text-sm` | `bg-card` | `ring-2 ring-ring` | Gallery search |
| **Panel search** | `h-[30px]` | `text-[12px]` | `bg-secondary` | `ring-1 ring-primary/40` | FilterMenuContent |
| **Compact inline** | auto (`py-0.5`) | `text-[11.5px]` | `bg-secondary` | `border-primary/50` | TagManagement |
| **Sidebar compact** | `h-6` | `text-xs` | `bg-secondary` | `ring-1 ring-primary/40` | ImageViewer scenes |

**Problems:**
1. The formal `<Input>` uses `bg-card` and `ring-ring` (the amber ring token); the inline inputs use `bg-secondary` and `ring-primary/40`. These are different background colours and different focus behaviours.
2. Focus ring: `ring-2` vs `ring-1` vs `border-only` — three different focus indicator approaches.
3. The documented standard in `visual-language.md` says `focus:ring-1 focus:ring-primary/40`, but the actual `<Input>` primitive doesn't follow this.

**Recommendation:** Create 3 codified input sizes (all using `bg-secondary` and `focus:ring-1 focus:ring-primary/40`):
- `input-default`: h-10, text-sm (Gallery search, forms)
- `input-compact`: h-[30px], text-[12px] (filter search bars, panel inputs)
- `input-inline`: h-6, text-xs (sidebar, in-row editing)

Update the `<Input>` primitive to use `bg-secondary` instead of `bg-card`, and `ring-1 ring-primary/40` instead of `ring-2 ring-ring`.

### 5b. Close buttons — 3 different implementations

| Component | Size | Icon size | StrokeWidth | Style |
|-----------|------|-----------|-------------|-------|
| TagManagement | `26×26px` (inline style) | `14×14` | 1.5 | Custom button |
| ImageViewer | `h-7 w-7` (Tailwind) | `h-4 w-4` | 2 (default) | Utility row button |
| DialogContent primitive | absolute positioning | `h-4 w-4` | 2 (default) | Radix pattern |

**Recommendation:** Standardise a single close button pattern. The TagManagement version (thinner stroke, slightly smaller) feels more refined. Suggest:
```tsx
<button className="h-7 w-7 rounded flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors">
  <X className="h-3.5 w-3.5" strokeWidth={1.5} />
</button>
```

### 5c. Confirmation dialogs — 2 different patterns

- **ImageViewer** uses `<ConfirmDialog>` from `ui/confirm-dialog.tsx` — a proper reusable component
- **TagManagement** uses a custom `<ConfirmOverlay>` — inline overlay with `bg-black/60 backdrop-blur-sm`

The ConfirmOverlay approach (in-panel overlay) is actually nicer for a dialog-within-a-dialog scenario — it avoids stacking two full-screen modals. But the implementations should converge: extract ConfirmOverlay into a shared component, or use ConfirmDialog everywhere.

### 5d. Count badges — 3 variants

| Location | Size | Style |
|----------|------|-------|
| GalleryFilterPanel button | `h-4 min-w-4 text-[10px]` | `bg-primary text-primary-foreground` (solid) |
| ImageViewer filter button | `h-3.5 w-3.5 text-[9px]` | `bg-primary text-primary-foreground` (solid) |
| Gallery type tabs | `text-[10px] px-1.5 py-px` | `bg-primary/15 text-primary` (tinted) |
| FilterMenuContent header | `h-[18px] px-[7px] text-[10px]` | `bg-primary/12 border-primary/25 text-primary` (tinted + border) |

**Recommendation:** Two tiers:
- **Solid badge** (for count overlays on buttons): `h-4 min-w-4 px-1 rounded-full bg-primary text-[10px] font-bold text-primary-foreground`
- **Tinted badge** (inline context labels): `px-1.5 py-px rounded-full bg-primary/15 text-[10px] font-medium text-primary`

---

## 6. Interaction Patterns

### 6a. Include / exclude filter model — strong and consistent

The click-to-include / right-click-to-exclude pattern is well-implemented in FilterMenuContent and carries through to the gallery filter chips. The visual vocabulary is clear:
- Include: amber (`bg-primary/20 text-primary border-primary/40`)
- Exclude: red (`bg-destructive/10 text-destructive border-destructive/30`) + `line-through`
- Neutral: category colour tint

### 6b. Inline editing — two patterns

- **ImageViewer name**: Click text → input replaces text, `bg-transparent border-b border-primary/70`, Enter/Escape/blur to commit. Pencil icon reveals on group hover.
- **TagManagement name/aliases**: Click text → input appears with Check/X buttons. `bg-secondary border-border rounded`.

The ImageViewer pattern (underline input) is more elegant for single-field editing. The TagManagement pattern (bordered input + confirm/cancel buttons) is appropriate for its more complex editing context. Both are valid, but they should be documented as "inline edit" vs "form edit" patterns.

### 6c. Tab/toggle active states — 3 different patterns (problem)

| Component | Active pattern |
|-----------|---------------|
| Gallery type tabs | `border-b-2 border-primary text-foreground` (underline tab) |
| ImageViewer Map/Scene toggle | `bg-primary/20 text-primary font-medium` (amber tinted) |
| ImageViewer scene type filter | `bg-secondary text-foreground font-medium` (neutral) |

The scene-type filter toggle in ImageViewer uses `bg-secondary` (neutral) instead of amber for the active state. This breaks the pattern established by every other toggle/tab in the app.

**Recommendation:** The Gallery tabs (underline) should remain distinct as page-level navigation. But segmented toggles should all use the amber pattern: `bg-primary/20 text-primary font-medium`.

### 6d. Hover using JS vs Tailwind (inconsistency)

FilterMenuContent's `CategoryNavItem` and `AuthorChecklist` use JavaScript `onMouseEnter`/`onMouseLeave` handlers to set `style.background` for hover states. TagManagement's category list uses Tailwind `hover:bg-[...]` classes.

Both achieve the same visual, but the JS approach is fragile (won't work with keyboard focus, harder to maintain). **Recommendation:** Use Tailwind hover classes everywhere. If the dynamic hsl value is needed, use a CSS custom property or the `[&:hover]:bg-[hsl(...)]` syntax.

---

## 7. Structural Patterns

### 7a. Two-column panel layout (strong pattern)

Both FilterMenuContent and TagManagementDialog use the same structural approach:
- Left sidebar: ~116-188px, `DARK_SURFACE` background, scrollable list, border-right
- Right content: `flex-1`, sections with headers, scrollable content area
- Header: `DARK_SURFACE`, Cinzel title + amber rule, action buttons right-aligned
- Footer: `DARK_SURFACE`, hint text left, action right

This is a solid reusable pattern that should be codified. The widths differ (116px vs 188px) which is fine — the narrower sidebar for filters makes sense given the simpler navigation items.

### 7b. Panel header pattern

All four components share a recognisable header structure:

```
┌────────────────────────────────────────────┐
│  Panel Title (Cinzel, 13px)    [actions]   │ ← DARK_SURFACE bg
│  ═══ (amber rule, 7w)                     │
└────────────────────────────────────────────┘
```

This is consistent between FilterMenuContent and TagManagement. The Gallery header is a variant (larger, with the page gradient). ImageViewer doesn't have this pattern (uses the amber stripe instead).

### 7c. Panel footer pattern

FilterMenuContent and TagManagement both have footers:
- FilterMenuContent: `"Right-click to exclude"` + `"Clear N filters"` button
- TagManagement: `"Click a value to rename it · click aliases to edit"`

Same structure: hint text left-aligned, optional action right-aligned, `DARK_SURFACE` background. Worth standardising.

---

## 8. Icon Usage

### 8a. Lucide icons — consistent library choice

All icons come from `lucide-react`. The curated `categoryIcons.ts` map (36 icons) is well-chosen for the TTRPG context (Castle, Sword, Shield, Crown, Skull, etc.).

### 8b. Icon sizing — generally consistent with one exception

Most icons use `h-3.5 w-3.5` for inline controls, `h-4 w-4` for primary actions, `h-3 w-3` for small/secondary elements. TagManagement frequently uses `style={{ width: N, height: N }}` instead of Tailwind classes — this works but is inconsistent with the rest of the codebase.

### 8c. strokeWidth inconsistency

- TagManagement: `strokeWidth={1.5}` on nearly all icons
- FilterMenuContent: default (2)
- ImageViewer: default (2)
- Gallery: default (2)

TagManagement's thinner strokes create a subtly more refined look. This is arguably better for the UI's overall tone, but it makes TagManagement feel slightly different from the other panels.

**Recommendation:** Either standardise on `strokeWidth={1.5}` everywhere for icons smaller than `h-4 w-4`, or accept the default. Don't mix.

---

## 9. Dead Code / Unused Patterns

### 9a. SearchBar.tsx is unused

The `SearchBar.tsx` component at `components/SearchBar.tsx` is not used anywhere — Gallery.tsx has its own inline search implementation. The SearchBar component is simpler and less featured than the Gallery version (no clear button, no mode icons, no inline filter integration).

**Recommendation:** Delete `SearchBar.tsx` or repurpose it as the canonical search input pattern.

### 9b. Card pattern documentation drift

`visual-language.md` documents `hover:scale-[1.03]` for card hover, but `SceneTile.tsx` uses `group-hover:scale-[1.05]`. Small difference but the doc should match reality.

---

## 10. Inline Styles vs Tailwind Classes

TagManagementDialog is the heaviest user of inline `style={{...}}` — it uses them for padding, width, height, background colours, border colours, border-radius, font-size, and margins. FilterMenuContent also uses them for several elements.

This isn't inherently wrong (pixel-precise values don't always map to Tailwind utilities), but it creates two styling paradigms in the same codebase. The `style={{}}` values:
- Are harder to search for
- Don't participate in Tailwind's responsive/dark-mode system
- Can't be overridden by className
- Make it harder to extract shared components

**Recommendation:** Migrate inline styles to Tailwind where possible. For values that don't map to Tailwind (like `padding: '7px 12px 7px 14px'`), consider whether the precision is actually needed or if `px-3 py-[7px]` would work.

---

## 11. Summary of Inconsistencies (Priority Order)

### High priority — RESOLVED

1. ~~**Input fields**: 4 different implementations~~ → CVA `<Input>` with 3 size variants (default/compact/sm), unified `bg-secondary` + `ring-1 ring-primary/40`
2. ~~**Section labels**: 3 different combinations~~ → `.section-label` utility class: `text-[10px] font-semibold tracking-[0.1em] uppercase text-muted-foreground`
3. ~~**DARK_SURFACE vs --popover**~~ → Deleted `DARK_SURFACE` constant; all uses replaced with `bg-popover` class or `hsl(var(--popover))`
4. ~~**Focus ring**: 3 different approaches~~ → All unified to `focus-visible:ring-1 focus-visible:ring-primary/40` across button, input, dialog, checkbox, sheet

### Medium priority — RESOLVED

5. ~~**Close button**: 3 implementations~~ → Unified to `h-7 w-7 rounded` with `h-3.5 w-3.5` icon and `hover:bg-secondary`
6. ~~**Tab/toggle active state**~~ → ImageViewer scene type filter now uses `bg-primary/20 text-primary` (amber)
7. ~~**Count badges**: 3-4 variants~~ → Standardised to 2 tiers: solid (button overlays) and tinted (inline context)
8. ~~**strokeWidth**~~ → Removed all `strokeWidth={1.5}` from TagManagement (18 instances), now uses default (2)
9. ~~**Amber rule sizes**~~ → Standardised to 2 tiers: page-level (`h-[1.5px] w-16`) and panel-level (`h-px w-7`)
10. **Confirmation dialogs**: Two different UI patterns. *(Not yet addressed — lower impact)*

### Low priority (style nits)

11. **Hover implementation**: JS event handlers vs Tailwind hover classes.
12. **Card scale factor**: doc says 1.03, code says 1.05.
13. **Font weight**: Gallery title `medium` vs ImageViewer name `semibold`.
14. **Inline styles vs Tailwind**: Paradigm mixing in TagManagement.

---

## 12. Resolution Status

All high and medium priority inconsistencies were resolved on 2026-02-26. See the implementation plan at `.claude/plans/squishy-giggling-wilkes.md` for full details.

### What was done (7 phases)
1. **Token cleanup**: Deleted `DARK_SURFACE` from both files, replaced ~30 raw HSL values across 5 files with `hsl(var(--token))` references. Added `--surface-canvas` token. Zero raw HSL values remain in any `.tsx` file.
2. **Input standardisation**: Rewrote `ui/input.tsx` with CVA variants (default/compact/sm). Updated FilterMenuContent and ImageViewer to use `<Input>`. Unified all focus rings to `ring-1 ring-primary/40` across button, input, dialog, checkbox, sheet.
3. **Section labels**: Added `.section-label` utility class to `index.css`. Replaced 9 instances across 3 files.
4. **Count badges**: Standardised to 2 tiers (solid overlays, tinted inline).
5. **Close buttons**: Unified to `h-7 w-7` with `h-3.5 w-3.5` icon and `hover:bg-secondary`.
6. **Toggle active states + strokeWidth + amber rules**: Fixed ImageViewer scene type toggle to use amber, removed 18 `strokeWidth={1.5}` overrides, standardised amber rule widths.
7. **Cleanup**: Deleted dead `SearchBar.tsx`, updated `visual-language.md` with all standards.

### Remaining low-priority items
- Confirmation dialogs: Two different UI patterns (ImportDialog vs ImageViewer delete)
- Hover implementation: Some JS event handlers vs Tailwind hover classes
- Card scale factor: doc says 1.03, code says 1.05
- Font weight: Gallery title `medium` vs ImageViewer name `semibold`
- Inline styles vs Tailwind: Some paradigm mixing remains in TagManagement

---

## 13. What NOT to Change

Some things that might look like inconsistencies but are actually correct:

- **ImageViewer using a custom fullscreen overlay instead of `<Dialog>`**: The viewer needs precise control over canvas sizing and keyboard navigation that the Dialog primitive doesn't support well.
- **FilterMenuContent's JS hover handlers**: These exist because the hover colour depends on state (active vs inactive). Tailwind can handle this with group variants, but the current approach works. Low priority to change.
- **Different sidebar widths (116px vs 188px)**: These serve different content needs and are fine.
- **TagManagement's ConfirmOverlay vs ConfirmDialog**: The in-panel overlay is actually better UX for nested dialogs. Consider promoting it to the shared UI library rather than replacing it.
- **Tag colour classes as static Tailwind strings**: The current approach works well for dark-only. When light mode arrives, this will need a second set of mappings, but pre-engineering that now would be premature. Just be aware of it.
- **The `darkMode: ["class"]` Tailwind config**: Already set up for class-based theme switching — this is the right foundation for a future `.light` / `.dark` toggle. No changes needed here.
