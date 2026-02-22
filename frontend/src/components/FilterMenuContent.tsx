/**
 * FilterMenuContent — shared popover body used by GalleryFilterPanel and FileToolbar.
 *
 * Two-column layout:
 *  Left  — scrollable category list with coloured dot indicators
 *  Right — coloured pill options for the selected category (or all)
 *
 * Interaction:
 *  Click pill = include; expanding "−" button on hover = exclude
 *  Clicking an active pill toggles it off (or switches mode)
 *  Popover stays open so users can add multiple filters in one session
 */

import { useState, useMemo, useRef, useEffect } from 'react'
import { Search, X, Check, Minus, Plus } from 'lucide-react'
import { DEFAULT_TAG_COLOR } from '@/components/import/tagColors'
import { useGetTagColor } from '@/contexts/TagColorContext'
import type { ActiveFilter } from '@/components/import/fileFilter'

// ─── Public types ─────────────────────────────────────────────────────────────

export interface FilterOption {
  filterValue: string // stored in ActiveFilter.value
  label: string // shown in the pill
  filterLabel: string // stored in ActiveFilter.label (chip text)
  count?: number
  aliases?: string[] // alias strings for search matching
}

export interface FilterOptionGroup {
  id: string // 'author' | 'gridded' | 'subgroup' | category name
  label: string // section heading (will be capitalised via CSS)
  type: ActiveFilter['type']
  options: FilterOption[]
}

interface FilterMenuContentProps {
  groups: FilterOptionGroup[]
  activeFilters: ActiveFilter[]
  onFiltersChange: (filters: ActiveFilter[]) => void
}

// Groups that are not tag categories — they don't get category colours
const NON_TAG_GROUPS = new Set([
  'author',
  'gridded',
  'subgroup',
  'color',
  'image_type',
  'media_type',
])

/**
 * Scores how well a filter option matches a search query.
 * Higher is a better match. Returns -1 if no match at all.
 *   5 — exact value match
 *   4 — value starts with query
 *   3 — exact alias match
 *   2 — value contains query
 *   1 — alias starts with query
 *   0 — alias contains query
 *  -1 — no match
 */
function optionMatchScore(label: string, aliases: string[], q: string): number {
  const l = label.toLowerCase()
  if (l === q) return 5
  if (l.startsWith(q)) return 4
  const aa = aliases.map((a) => a.toLowerCase())
  if (aa.some((a) => a === q)) return 3
  if (l.includes(q)) return 2
  if (aa.some((a) => a.startsWith(q))) return 1
  if (aa.some((a) => a.includes(q))) return 0
  return -1
}

// ─── Main component ────────────────────────────────────────────────────────────

export function FilterMenuContent({
  groups,
  activeFilters,
  onFiltersChange,
}: FilterMenuContentProps) {
  const getTagColor = useGetTagColor()
  const [search, setSearch] = useState('')
  const [tab, setTab] = useState('all')
  const [customColors, setCustomColors] = useState<string[]>(loadCustomColors)

  const searchLower = search.toLowerCase()

  // Groups to show on the right panel, filtered by selected tab + search text
  const visibleGroups = useMemo(() => {
    const byTab = tab === 'all' ? groups : groups.filter((g) => g.id === tab)
    if (!searchLower) return byTab
    return byTab
      .map((g) => {
        // If the category name matches, show all its options unranked (as before)
        if (g.label.toLowerCase().includes(searchLower)) return g

        // Otherwise score each option and keep only matches, sorted best-first
        const scored = g.options
          .map((o) => ({ o, s: optionMatchScore(o.label, o.aliases ?? [], searchLower) }))
          .filter(({ s }) => s >= 0)
        if (scored.length === 0) return { ...g, options: [] }
        scored.sort((a, b) => b.s - a.s)
        return { ...g, options: scored.map(({ o }) => o) }
      })
      .filter((g) => g.options.length > 0)
  }, [groups, tab, searchLower])

  // ── Filter helpers ────────────────────────────────────────────────────────

  const getActiveState = (
    type: ActiveFilter['type'],
    filterValue: string,
  ): 'include' | 'exclude' | null => {
    const f = activeFilters.find((af) => af.type === type && af.value === filterValue)
    if (!f) return null
    return f.exclude ? 'exclude' : 'include'
  }

  /** Click pill: not active → include; excluded → switch to include; included → remove */
  const handleInclude = (group: FilterOptionGroup, opt: FilterOption) => {
    const existing = activeFilters.find(
      (af) => af.type === group.type && af.value === opt.filterValue,
    )
    if (!existing) {
      onFiltersChange([
        ...activeFilters,
        { type: group.type, value: opt.filterValue, label: opt.filterLabel, exclude: false },
      ])
    } else if (existing.exclude) {
      onFiltersChange(
        activeFilters.map((af) =>
          af.type === group.type && af.value === opt.filterValue ? { ...af, exclude: false } : af,
        ),
      )
    } else {
      onFiltersChange(
        activeFilters.filter((af) => !(af.type === group.type && af.value === opt.filterValue)),
      )
    }
  }

  /** Right-click: not active → exclude; included → switch to exclude; excluded → remove */
  const handleExclude = (e: React.MouseEvent, group: FilterOptionGroup, opt: FilterOption) => {
    e.preventDefault()
    e.stopPropagation()
    const existing = activeFilters.find(
      (af) => af.type === group.type && af.value === opt.filterValue,
    )
    if (!existing) {
      onFiltersChange([
        ...activeFilters,
        { type: group.type, value: opt.filterValue, label: opt.filterLabel, exclude: true },
      ])
    } else if (!existing.exclude) {
      onFiltersChange(
        activeFilters.map((af) =>
          af.type === group.type && af.value === opt.filterValue ? { ...af, exclude: true } : af,
        ),
      )
    } else {
      onFiltersChange(
        activeFilters.filter((af) => !(af.type === group.type && af.value === opt.filterValue)),
      )
    }
  }

  // How many active filters exist for a given group
  // For color groups, count all color filters (including custom colors not in the palette)
  const groupActiveCount = (group: FilterOptionGroup) =>
    group.type === 'color'
      ? activeFilters.filter((af) => af.type === 'color').length
      : activeFilters.filter(
          (af) => af.type === group.type && group.options.some((o) => o.filterValue === af.value),
        ).length

  const totalActive = activeFilters.length

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div className="flex flex-col min-h-0 h-full">
      {/* Search bar — full width at top */}
      <div className="px-2 py-1.5 border-b border-border/50 flex-shrink-0">
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3 w-3 text-muted-foreground pointer-events-none" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search filters…"
            className="w-full h-7 pl-7 pr-6 text-xs bg-secondary border border-border rounded-md focus:outline-none focus:ring-1 focus:ring-primary/40 focus:border-primary/50 text-foreground placeholder:text-muted-foreground"
          />
          {search && (
            <button
              onClick={() => setSearch('')}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors"
            >
              <X className="h-3 w-3" />
            </button>
          )}
        </div>
      </div>

      {/* Two-column body */}
      <div className="flex flex-1 min-h-0 overflow-hidden">
        {/* Left — category navigator */}
        <div className="w-28 flex-shrink-0 border-r border-border/50 overflow-y-auto py-1">
          <CategoryNavItem
            label="All"
            active={tab === 'all'}
            activeCount={totalActive}
            colorId={null}
            onClick={() => setTab('all')}
          />

          {/* Divider between meta and tag groups */}
          {groups.some((g) => NON_TAG_GROUPS.has(g.id)) &&
            groups.some((g) => !NON_TAG_GROUPS.has(g.id)) && (
              <div className="mx-2 my-1 border-t border-border/50" />
            )}

          {groups.map((g) => (
            <CategoryNavItem
              key={g.id}
              label={g.label}
              active={tab === g.id}
              activeCount={groupActiveCount(g)}
              colorId={NON_TAG_GROUPS.has(g.id) ? null : g.id}
              onClick={() => setTab(g.id)}
            />
          ))}
        </div>

        {/* Right — option pills */}
        <div className="flex-1 overflow-y-auto min-w-0">
          {visibleGroups.length === 0 && (
            <p className="px-3 py-5 text-xs text-muted-foreground text-center">
              {search ? `No results for "${search}"` : 'No options available'}
            </p>
          )}

          {visibleGroups.map((group) => {
            const colorId = NON_TAG_GROUPS.has(group.id) ? null : group.id
            const colors = colorId ? getTagColor(colorId) : DEFAULT_TAG_COLOR

            return (
              <div key={group.id}>
                {/* Only show section heading in "All" mode (multiple groups visible) */}
                {tab === 'all' && (
                  <div className="px-3 pt-3 pb-1.5">
                    <span
                      className={`text-[11px] font-semibold tracking-wider uppercase capitalize ${colors.text}`}
                    >
                      {group.label}
                    </span>
                  </div>
                )}

                {group.type === 'color' ? (
                  <div
                    className={`grid grid-cols-6 gap-2 px-3 pb-3 ${tab !== 'all' ? 'pt-3' : ''}`}
                  >
                    {group.options.map((opt) => {
                      const state = getActiveState(group.type, opt.filterValue)
                      return (
                        <ColorSwatch
                          key={opt.filterValue}
                          hex={opt.filterValue}
                          label={opt.label}
                          activeState={state}
                          onInclude={() => handleInclude(group, opt)}
                          onExclude={(e) => handleExclude(e, group, opt)}
                        />
                      )
                    })}
                    {customColors.map((hex) => {
                      const state = getActiveState(group.type, hex)
                      const opt: FilterOption = { filterValue: hex, label: hex, filterLabel: hex }
                      return (
                        <ColorSwatch
                          key={`custom-${hex}`}
                          hex={hex}
                          label={hex}
                          activeState={state}
                          onInclude={() => handleInclude(group, opt)}
                          onExclude={(e) => handleExclude(e, group, opt)}
                          onRemove={() => {
                            const updated = customColors.filter((c) => c !== hex)
                            setCustomColors(updated)
                            saveCustomColors(updated)
                            // Also remove filter if active
                            onFiltersChange(
                              activeFilters.filter(
                                (af) => !(af.type === 'color' && af.value === hex),
                              ),
                            )
                          }}
                        />
                      )
                    })}
                    <CustomColorPicker
                      onSelect={(hex) => {
                        const opt: FilterOption = { filterValue: hex, label: hex, filterLabel: hex }
                        handleInclude(group, opt)
                      }}
                      customColors={customColors}
                      onCustomColorsChange={setCustomColors}
                    />
                  </div>
                ) : (
                  <div
                    className={`flex flex-wrap gap-1.5 pl-3 pr-3 pb-3 ${tab !== 'all' ? 'pt-3' : ''}`}
                  >
                    {group.options.map((opt) => {
                      const state = getActiveState(group.type, opt.filterValue)
                      return (
                        <OptionPill
                          key={opt.filterValue}
                          label={opt.label}
                          count={opt.count}
                          activeState={state}
                          colorId={colorId}
                          onInclude={() => handleInclude(group, opt)}
                          onExclude={(e) => handleExclude(e, group, opt)}
                        />
                      )
                    })}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

// ─── FilterChipList ────────────────────────────────────────────────────────────

interface FilterChipListProps {
  filters: ActiveFilter[]
  onFiltersChange: (filters: ActiveFilter[]) => void
}

export function FilterChipList({ filters, onFiltersChange }: FilterChipListProps) {
  if (filters.length === 0) return null

  const toggle = (i: number) =>
    onFiltersChange(filters.map((f, j) => (j === i ? { ...f, exclude: !f.exclude } : f)))

  const remove = (i: number) => onFiltersChange(filters.filter((_, j) => j !== i))

  return (
    <div className="flex flex-wrap gap-1">
      {filters.map((af, i) => (
        <FilterChip key={i} filter={af} onToggle={() => toggle(i)} onRemove={() => remove(i)} />
      ))}
      {filters.length > 1 && (
        <button
          onClick={() => onFiltersChange([])}
          className="text-xs text-muted-foreground hover:text-foreground px-1 transition-colors"
        >
          Clear all
        </button>
      )}
    </div>
  )
}

// ─── Sub-components ────────────────────────────────────────────────────────────

function CategoryNavItem({
  label,
  active,
  activeCount,
  colorId,
  onClick,
}: {
  label: string
  active: boolean
  activeCount: number
  colorId: string | null
  onClick: () => void
}) {
  const getTagColor = useGetTagColor()
  const colors = colorId ? getTagColor(colorId) : DEFAULT_TAG_COLOR

  return (
    <button
      onClick={onClick}
      className={`w-full flex items-center gap-1.5 px-2.5 py-1.5 text-left text-xs transition-colors
        border-l-2 ${
          active
            ? `${colors.bg} ${colors.text} font-medium ${colors.border}`
            : 'text-muted-foreground hover:bg-secondary border-transparent hover:text-foreground'
        }`}
    >
      {colorId && <span className={`h-2 w-2 rounded-full flex-shrink-0 ${colors.dot}`} />}
      <span className="capitalize truncate flex-1">{label}</span>
      {activeCount > 0 && (
        <span
          className={`text-[10px] font-semibold tabular-nums flex-shrink-0 ${active ? colors.text : 'text-muted-foreground'}`}
        >
          {activeCount}
        </span>
      )}
    </button>
  )
}

function OptionPill({
  label,
  count,
  activeState,
  colorId,
  onInclude,
  onExclude,
}: {
  label: string
  count?: number
  activeState: 'include' | 'exclude' | null
  colorId: string | null
  onInclude: () => void
  onExclude: (e: React.MouseEvent) => void
}) {
  const getTagColor = useGetTagColor()
  const colors = colorId ? getTagColor(colorId) : DEFAULT_TAG_COLOR

  if (activeState === 'include') {
    return (
      <button
        onClick={onInclude}
        onContextMenu={onExclude}
        title={`${label} — click to remove, right-click to exclude`}
        className="inline-flex items-center gap-1 h-6 px-2.5 rounded-full bg-primary/20 border border-primary/40 text-primary text-xs font-medium hover:bg-primary/30 transition-colors"
      >
        <Check className="h-3 w-3 flex-shrink-0" />
        <span className="capitalize max-w-[160px] truncate">{label}</span>
      </button>
    )
  }

  if (activeState === 'exclude') {
    return (
      <button
        onClick={onInclude}
        onContextMenu={onExclude}
        title={`${label} — click to include, right-click to remove`}
        className="inline-flex items-center gap-1 h-6 px-2.5 rounded-full bg-destructive/10 border border-destructive/30 text-destructive text-xs hover:bg-destructive/20 transition-colors"
      >
        <Minus className="h-3 w-3 flex-shrink-0" />
        <span className="capitalize max-w-[160px] truncate line-through">{label}</span>
      </button>
    )
  }

  // Normal state — left-click to include, right-click to exclude
  return (
    <button
      onClick={onInclude}
      onContextMenu={onExclude}
      title={`${label} — right-click to exclude`}
      className={`inline-flex items-center gap-1 h-6 px-2.5 rounded-full border ${colors.border} ${colors.bg} ${colors.text} text-xs hover:brightness-110 transition-colors`}
    >
      <span className="capitalize max-w-[160px] truncate">{label}</span>
      {count !== undefined && (
        <span className="ml-0.5 text-[9px] opacity-50 tabular-nums">{count}</span>
      )}
    </button>
  )
}

function ColorSwatch({
  hex,
  label,
  activeState,
  onInclude,
  onExclude,
  onRemove,
}: {
  hex: string
  label: string
  activeState: 'include' | 'exclude' | null
  onInclude: () => void
  onExclude: (e: React.MouseEvent) => void
  onRemove?: () => void
}) {
  return (
    <div className="relative group">
      <button
        onClick={onInclude}
        onContextMenu={onExclude}
        title={`${label} — ${activeState === 'include' ? 'click to remove' : activeState === 'exclude' ? 'click to include' : 'right-click to exclude'}`}
        className={`aspect-square w-full rounded border-2 transition-all ${
          activeState === 'include'
            ? 'ring-2 ring-primary ring-offset-2 ring-offset-background border-primary scale-105'
            : activeState === 'exclude'
              ? 'ring-2 ring-destructive ring-offset-2 ring-offset-background border-destructive opacity-30'
              : 'border-border/40 hover:border-foreground/50 hover:scale-105'
        }`}
        style={{ backgroundColor: hex }}
      />
      {onRemove && (
        <button
          onClick={onRemove}
          className="absolute -top-1 -right-1 h-3.5 w-3.5 rounded-full bg-destructive text-destructive-foreground flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"
          title="Remove custom color"
        >
          <X className="h-2 w-2" />
        </button>
      )}
    </div>
  )
}

const CUSTOM_COLORS_KEY = 'color-filter-custom-colors'

function loadCustomColors(): string[] {
  try {
    const stored = localStorage.getItem(CUSTOM_COLORS_KEY)
    return stored ? JSON.parse(stored) : []
  } catch {
    return []
  }
}

function saveCustomColors(colors: string[]) {
  localStorage.setItem(CUSTOM_COLORS_KEY, JSON.stringify(colors))
}

function CustomColorPicker({
  onSelect,
  customColors,
  onCustomColorsChange,
}: {
  onSelect: (hex: string) => void
  customColors: string[]
  onCustomColorsChange: (colors: string[]) => void
}) {
  const inputRef = useRef<HTMLInputElement>(null)

  // Use native 'change' event (fires on dialog close) instead of React onChange
  // (which maps to DOM 'input' and fires on every drag)
  const onSelectRef = useRef(onSelect)
  onSelectRef.current = onSelect
  const customColorsRef = useRef(customColors)
  customColorsRef.current = customColors
  const onCustomColorsChangeRef = useRef(onCustomColorsChange)
  onCustomColorsChangeRef.current = onCustomColorsChange

  useEffect(() => {
    const el = inputRef.current
    if (!el) return
    const handler = () => {
      const hex = el.value
      const cc = customColorsRef.current
      if (!cc.includes(hex)) {
        const updated = [...cc, hex]
        onCustomColorsChangeRef.current(updated)
        saveCustomColors(updated)
      }
      onSelectRef.current(hex)
    }
    el.addEventListener('change', handler)
    return () => el.removeEventListener('change', handler)
  }, [])

  return (
    <button
      onClick={() => inputRef.current?.click()}
      title="Pick a custom color"
      className="aspect-square w-full rounded border-2 border-dashed border-border/60 hover:border-foreground/50 transition-all flex items-center justify-center bg-secondary/50 hover:bg-secondary"
    >
      <Plus className="h-3.5 w-3.5 text-muted-foreground" />
      <input ref={inputRef} type="color" className="sr-only" />
    </button>
  )
}

function FilterChip({
  filter,
  onToggle,
  onRemove,
}: {
  filter: ActiveFilter
  onToggle: () => void
  onRemove: () => void
}) {
  const getTagColor = useGetTagColor()
  const category = filter.type === 'tag' ? filter.value.split(':')[0] : null
  const colors = category ? getTagColor(category) : null

  if (filter.exclude) {
    return (
      <span
        className="inline-flex items-center gap-1 text-xs rounded-full border border-destructive/30 bg-destructive/10 text-destructive px-2 py-0.5"
        title={filter.label}
      >
        {filter.type === 'color' && (
          <span
            className="h-3 w-3 rounded-sm border border-black/25 shrink-0 opacity-50"
            style={{ backgroundColor: filter.value }}
          />
        )}
        <span className="capitalize opacity-75 line-through max-w-[130px] truncate">
          {filter.label}
        </span>
        <button
          onClick={onToggle}
          className="opacity-60 hover:opacity-100 text-[10px] font-medium transition-opacity"
          title="Switch to include"
        >
          hidden
        </button>
        <button
          onClick={onRemove}
          className="hover:opacity-80 transition-opacity ml-0.5"
          title="Remove"
        >
          <X className="h-2.5 w-2.5" />
        </button>
      </span>
    )
  }

  const chipClasses = colors
    ? `border ${colors.border} ${colors.bg} ${colors.text}`
    : 'border border-primary/30 bg-primary/10 text-primary'

  return (
    <span
      className={`inline-flex items-center gap-1 text-xs rounded-full px-2 py-0.5 ${chipClasses}`}
      title={filter.label}
    >
      {filter.type === 'color' && (
        <span
          className="h-3 w-3 rounded-sm border border-black/25 shrink-0"
          style={{ backgroundColor: filter.value }}
        />
      )}
      <span className="capitalize max-w-[130px] truncate">{filter.label}</span>
      <button
        onClick={onToggle}
        className="opacity-50 hover:opacity-100 text-[10px] font-medium transition-opacity"
        title="Switch to exclude"
      >
        only
      </button>
      <button
        onClick={onRemove}
        className="hover:opacity-80 transition-opacity ml-0.5"
        title="Remove"
      >
        <X className="h-2.5 w-2.5" />
      </button>
    </span>
  )
}
