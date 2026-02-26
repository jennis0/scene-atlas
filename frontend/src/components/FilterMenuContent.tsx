/**
 * FilterMenuContent — shared popover body used by GalleryFilterPanel and FileToolbar.
 *
 * Layout (top-to-bottom):
 *  1. Panel header — Cinzel "Filters" title + active badge
 *  2. Search bar
 *  3. Two-column body (left nav + right content)
 *  4. Footer — hint text + clear button
 *
 * Right panel per category type:
 *  author   → compact checklist rows
 *  gridded  → visual tile selector
 *  color    → colour swatches
 *  other    → coloured pills
 *
 * Interaction:
 *  Click = include; right-click = exclude
 *  Clicking an active item toggles it off (or switches mode)
 */

import { useState, useMemo, useRef, useEffect } from 'react'
import {
  Search,
  X,
  Check,
  Minus,
  Plus,
  User,
  LayoutGrid,
  Palette,
  Film,
  Image as ImageIcon,
  Tag,
  Layers,
  type LucideIcon,
} from 'lucide-react'
import { Input } from '@/components/ui/input'
import { DEFAULT_TAG_COLOR } from '@/components/import/tagColors'
import { useGetTagColor } from '@/contexts/TagColorContext'
import { getCategoryIcon } from '@/lib/categoryIcons'
import type { ActiveFilter } from '@/components/import/fileFilter'

// ─── Public types ─────────────────────────────────────────────────────────────

export interface FilterOption {
  filterValue: string // stored in ActiveFilter.value
  label: string // shown in the pill / row
  filterLabel: string // stored in ActiveFilter.label (chip text)
  count?: number
  aliases?: string[] // alias strings for search matching
}

export interface FilterOptionGroup {
  id: string // 'author' | 'gridded' | 'subgroup' | category name
  label: string // section heading
  type: ActiveFilter['type']
  options: FilterOption[]
  iconName?: string | null // Lucide icon name for tag category groups
}

interface FilterMenuContentProps {
  groups: FilterOptionGroup[]
  activeFilters: ActiveFilter[]
  onFiltersChange: (filters: ActiveFilter[]) => void
}

// Groups that are not tag categories
const NON_TAG_GROUPS = new Set([
  'author',
  'gridded',
  'subgroup',
  'color',
  'image_type',
  'media_type',
])

// Icons for each known non-tag group
const GROUP_ICONS: Record<string, LucideIcon> = {
  author: User,
  gridded: LayoutGrid,
  color: Palette,
  media_type: Film,
  image_type: ImageIcon,
  subgroup: Tag,
}

function getGroupIcon(id: string, iconName?: string | null): LucideIcon {
  if (!NON_TAG_GROUPS.has(id) && iconName) return getCategoryIcon(iconName)
  return GROUP_ICONS[id] ?? Tag
}

// Display labels for grid filter tiles
const GRID_TILE_CONFIG: Record<string, { label: string }> = {
  square: { label: 'Square' },
  hex: { label: 'Hex' },
  gridded: { label: 'Any Grid' },
  gridless: { label: 'No Grid' },
  unknown: { label: 'Unknown' },
}

// Darker surface colour shared by the nav and footer — uses --popover token
const DARK_SURFACE = 'hsl(var(--popover))'

/**
 * Scores how well a filter option matches a search query.
 * Higher is better; -1 means no match.
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
  const scrollRef = useRef<HTMLDivElement>(null)

  // Reset scroll position when switching tabs so you don't land mid-page
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: 0 })
  }, [tab])

  const searchLower = search.toLowerCase()

  const nonTagGroups = useMemo(() => groups.filter((g) => NON_TAG_GROUPS.has(g.id)), [groups])
  const tagGroups = useMemo(() => groups.filter((g) => !NON_TAG_GROUPS.has(g.id)), [groups])

  // Groups to show on the right panel, filtered by selected tab + search text
  const visibleGroups = useMemo(() => {
    const byTab = tab === 'all' ? groups : groups.filter((g) => g.id === tab)
    if (!searchLower) return byTab
    return byTab
      .map((g) => {
        if (g.label.toLowerCase().includes(searchLower)) return g
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

  const groupActiveCount = (group: FilterOptionGroup) =>
    group.type === 'color'
      ? activeFilters.filter((af) => af.type === 'color').length
      : activeFilters.filter(
          (af) => af.type === group.type && group.options.some((o) => o.filterValue === af.value),
        ).length

  const totalActive = activeFilters.length

  // Selected group info for "Filter by [Category]" header
  const selectedGroup = tab === 'all' ? null : (groups.find((g) => g.id === tab) ?? null)
  const selectedIsTag = selectedGroup ? !NON_TAG_GROUPS.has(selectedGroup.id) : false
  const selectedColors = selectedGroup
    ? selectedIsTag
      ? getTagColor(selectedGroup.id)
      : DEFAULT_TAG_COLOR
    : null
  const SelectedIcon = selectedGroup ? getGroupIcon(selectedGroup.id, selectedGroup.iconName) : null

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div className="flex flex-col min-h-0 h-full">
      {/* ── Panel header ── */}
      <div
        className="px-4 py-3 border-b border-border/60 flex-shrink-0 flex items-end justify-between"
        style={{ background: DARK_SURFACE }}
      >
        <div>
          <div className="flex items-center gap-2">
            <span className="font-display text-[13px] font-medium tracking-[0.06em] text-foreground">
              Filters
            </span>
            {totalActive > 0 && (
              <span className="inline-flex items-center px-1.5 py-px rounded-full bg-primary/15 text-[10px] font-medium text-primary tabular-nums">
                {totalActive} active
              </span>
            )}
          </div>
          <div className="mt-[3px] h-px w-7 bg-gradient-to-r from-primary to-transparent" />
        </div>
        {totalActive > 0 && (
          <button
            onClick={() => onFiltersChange([])}
            className="text-[11px] text-muted-foreground hover:text-foreground transition-colors pb-0.5"
          >
            Clear all
          </button>
        )}
      </div>

      {/* ── Search bar ── */}
      <div className="px-3 py-2 border-b border-border/50 flex-shrink-0">
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3 w-3 text-muted-foreground pointer-events-none" />
          <Input
            inputSize="compact"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search filters…"
            className="pl-7 pr-6"
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

      {/* ── Two-column body ── */}
      <div className="flex flex-1 min-h-0 overflow-hidden">
        {/* Left — category navigator */}
        <div
          className="w-[116px] flex-shrink-0 border-r border-border/60 overflow-y-auto py-[6px]"
          style={{ background: DARK_SURFACE }}
        >
          <CategoryNavItem
            label="All"
            active={tab === 'all'}
            activeCount={totalActive}
            colorId={null}
            icon={Layers}
            onClick={() => setTab('all')}
          />

          {groups.length > 0 && <div className="mx-2 my-1 h-px bg-border/50" />}

          {nonTagGroups.map((g) => (
            <CategoryNavItem
              key={g.id}
              label={g.label}
              active={tab === g.id}
              activeCount={groupActiveCount(g)}
              colorId={null}
              icon={getGroupIcon(g.id)}
              onClick={() => setTab(g.id)}
            />
          ))}

          {nonTagGroups.length > 0 && tagGroups.length > 0 && (
            <div className="mx-2 my-1 h-px bg-border/50" />
          )}

          {tagGroups.map((g) => (
            <CategoryNavItem
              key={g.id}
              label={g.label}
              active={tab === g.id}
              activeCount={groupActiveCount(g)}
              colorId={g.id}
              icon={getCategoryIcon(g.iconName)}
              onClick={() => setTab(g.id)}
            />
          ))}
        </div>

        {/* Right — option content */}
        <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
          {/* "Filter by [Icon] Category" header — single tab only */}
          {selectedGroup && SelectedIcon && selectedColors && (
            <div className="px-3.5 pt-3.5 pb-2.5 border-b border-border/50 flex-shrink-0 flex items-end justify-between">
              <div>
                <p className="section-label mb-0.5">Filter by</p>
                <div
                  className={`flex items-center gap-[7px] font-display text-[17px] font-medium tracking-[0.04em] leading-none ${selectedColors.text}`}
                >
                  <SelectedIcon className="h-3.5 w-3.5 flex-shrink-0 opacity-80" />
                  <span className="capitalize">{selectedGroup.label}</span>
                </div>
                <div className="mt-[3px] h-px w-7 bg-gradient-to-r from-primary to-transparent" />
              </div>
              {selectedGroup.type !== 'color' && (
                <span className="text-[11px] text-muted-foreground pb-0.5">
                  {selectedGroup.options.length} options
                </span>
              )}
            </div>
          )}

          {/* Options area */}
          <div ref={scrollRef} className="flex-1 overflow-y-auto min-w-0 [scrollbar-gutter:stable]">
            {visibleGroups.length === 0 && (
              <p className="px-3 py-5 text-xs text-muted-foreground text-center">
                {search ? `No results for "${search}"` : 'No options available'}
              </p>
            )}

            {visibleGroups.map((group, groupIdx) => {
              const colorId = NON_TAG_GROUPS.has(group.id) ? null : group.id
              const colors = colorId ? getTagColor(colorId) : DEFAULT_TAG_COLOR
              const isNonTag = colorId === null
              // Non-tag groups (Author, Grid, Color…) use amber primary in section headings
              const headingText = isNonTag ? 'text-primary/70' : colors.text

              return (
                <div key={group.id}>
                  {/* Section heading — only in "All" mode */}
                  {tab === 'all' && (
                    <div className={`px-3.5 pb-1.5 ${groupIdx === 0 ? 'pt-3' : 'pt-3.5'}`}>
                      {groupIdx > 0 && <div className="mb-2.5 border-t border-border/30" />}
                      <div
                        className={`flex items-center gap-[6px] font-display text-[13px] font-medium tracking-[0.04em] leading-none ${headingText}`}
                      >
                        {(() => {
                          const SectionIcon = getGroupIcon(group.id, group.iconName)
                          return <SectionIcon className="h-3 w-3 flex-shrink-0 opacity-75" />
                        })()}
                        <span className="capitalize">{group.label}</span>
                      </div>
                    </div>
                  )}

                  {group.type === 'author' ? (
                    <AuthorChecklist
                      group={group}
                      getActiveState={getActiveState}
                      onInclude={handleInclude}
                      onExclude={handleExclude}
                    />
                  ) : group.type === 'gridded' ? (
                    <GridTileSelector
                      group={group}
                      getActiveState={getActiveState}
                      onInclude={handleInclude}
                      onExclude={handleExclude}
                      compact={tab === 'all'}
                    />
                  ) : group.type === 'color' ? (
                    <div
                      className={`grid grid-cols-6 gap-2 px-3.5 pb-3.5 ${tab !== 'all' ? 'pt-3.5' : 'pt-1'}`}
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
                          const opt: FilterOption = {
                            filterValue: hex,
                            label: hex,
                            filterLabel: hex,
                          }
                          handleInclude(group, opt)
                        }}
                        customColors={customColors}
                        onCustomColorsChange={setCustomColors}
                      />
                    </div>
                  ) : (
                    <div
                      className={`flex flex-wrap gap-1.5 px-3.5 pb-3 ${tab !== 'all' ? 'pt-3' : 'pt-1'}`}
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

      {/* ── Footer ── */}
      <div
        className="px-3.5 py-2 border-t border-border/60 flex-shrink-0 flex items-center justify-between"
        style={{ background: DARK_SURFACE }}
      >
        <span className="text-[10.5px] text-muted-foreground italic">Right-click to exclude</span>
        {totalActive > 0 && (
          <button
            onClick={() => onFiltersChange([])}
            className="inline-flex items-center gap-[5px] h-[26px] px-2.5 rounded border border-border/70 text-[11px] text-muted-foreground hover:text-foreground hover:border-border transition-colors"
          >
            <X className="h-[9px] w-[9px]" />
            Clear {totalActive} filter{totalActive !== 1 ? 's' : ''}
          </button>
        )}
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

// ─── CategoryNavItem ──────────────────────────────────────────────────────────

function CategoryNavItem({
  label,
  active,
  activeCount,
  colorId,
  icon: Icon,
  onClick,
}: {
  label: string
  active: boolean
  activeCount: number
  colorId: string | null
  icon: LucideIcon
  onClick: () => void
}) {
  const getTagColor = useGetTagColor()
  // null = system group (Author, Grid, Color…) → primary amber when active
  // set  = tag category → use its assigned color
  const colors = colorId ? getTagColor(colorId) : null

  const activeClass = colors
    ? `${colors.bg} ${colors.text} font-medium ${colors.border}`
    : 'bg-muted text-foreground font-medium border-primary/60'

  return (
    <button
      onClick={onClick}
      style={{ padding: '7px 10px 7px 12px' }}
      className={`w-full flex items-center gap-[7px] text-left text-[12px] transition-colors border-l-2 ${
        active ? activeClass : 'text-muted-foreground hover:text-foreground border-transparent'
      }`}
      onMouseEnter={(e) => {
        if (!active) (e.currentTarget as HTMLElement).style.background = 'hsl(var(--muted))'
      }}
      onMouseLeave={(e) => {
        if (!active) (e.currentTarget as HTMLElement).style.background = ''
      }}
    >
      {/* Tag-category icons retain their colour even when inactive */}
      <Icon
        className={`h-3.5 w-3.5 flex-shrink-0 ${
          active ? '' : colors ? `${colors.text} opacity-60` : 'opacity-50'
        }`}
      />
      <span className="truncate flex-1 capitalize">{label}</span>
      {activeCount > 0 && (
        <span
          className={`text-[10px] font-semibold tabular-nums flex-shrink-0 ${
            active ? (colors ? colors.text : 'text-primary/80') : 'text-muted-foreground'
          }`}
        >
          {activeCount}
        </span>
      )}
    </button>
  )
}

// ─── AuthorChecklist ──────────────────────────────────────────────────────────

function AuthorChecklist({
  group,
  getActiveState,
  onInclude,
  onExclude,
}: {
  group: FilterOptionGroup
  getActiveState: (type: ActiveFilter['type'], value: string) => 'include' | 'exclude' | null
  onInclude: (group: FilterOptionGroup, opt: FilterOption) => void
  onExclude: (e: React.MouseEvent, group: FilterOptionGroup, opt: FilterOption) => void
}) {
  return (
    <div className="flex flex-col">
      {group.options.map((opt) => {
        const state = getActiveState(group.type, opt.filterValue)
        return (
          <button
            key={opt.filterValue}
            onClick={() => onInclude(group, opt)}
            onContextMenu={(e) => onExclude(e, group, opt)}
            title={`${opt.label}${opt.count !== undefined ? ` (${opt.count})` : ''} — right-click to exclude`}
            className={`w-full h-8 flex items-center text-left text-[12.5px] border-l-2 transition-colors ${
              state === 'include'
                ? 'border-l-primary text-foreground'
                : state === 'exclude'
                  ? 'border-l-destructive text-destructive/70'
                  : 'border-l-transparent text-muted-foreground'
            }`}
            style={{
              padding: '0 14px 0 10px',
              backgroundColor:
                state === 'include'
                  ? 'hsl(var(--primary) / 0.06)'
                  : state === 'exclude'
                    ? 'hsl(var(--destructive) / 0.05)'
                    : undefined,
            }}
            onMouseEnter={(e) => {
              if (!state)
                (e.currentTarget as HTMLElement).style.backgroundColor = 'hsl(var(--muted))'
            }}
            onMouseLeave={(e) => {
              if (!state) (e.currentTarget as HTMLElement).style.backgroundColor = ''
            }}
          >
            {/* Checkbox */}
            <span
              className={`h-3.5 w-3.5 flex-shrink-0 mr-[9px] flex items-center justify-center rounded-[3px] ${
                state === 'include'
                  ? 'bg-primary border border-primary'
                  : state === 'exclude'
                    ? 'bg-destructive/15 border border-destructive/50'
                    : 'border border-border'
              }`}
            >
              {state === 'include' && <Check className="h-[9px] w-[9px] text-primary-foreground" />}
              {state === 'exclude' && <Minus className="h-[9px] w-[9px] text-destructive" />}
            </span>

            {/* Name */}
            <span
              className={`flex-1 truncate ${state === 'exclude' ? 'line-through opacity-60' : ''}`}
            >
              {opt.label}
            </span>

            {/* Count */}
            {opt.count !== undefined && (
              <span
                className={`text-[10.5px] flex-shrink-0 tabular-nums ${
                  state === 'include' ? 'text-primary/70' : 'text-muted-foreground'
                }`}
              >
                {opt.count.toLocaleString()}
              </span>
            )}
          </button>
        )
      })}
    </div>
  )
}

// ─── GridTileSelector ─────────────────────────────────────────────────────────

function GridTileSelector({
  group,
  getActiveState,
  onInclude,
  onExclude,
  compact = false,
}: {
  group: FilterOptionGroup
  getActiveState: (type: ActiveFilter['type'], value: string) => 'include' | 'exclude' | null
  onInclude: (group: FilterOptionGroup, opt: FilterOption) => void
  onExclude: (e: React.MouseEvent, group: FilterOptionGroup, opt: FilterOption) => void
  compact?: boolean
}) {
  return (
    <div>
      {/* 3-column compact layout — fits all 5 tiles in 2 rows */}
      <div className={`grid grid-cols-3 gap-1.5 px-3 pb-3 ${compact ? 'pt-1' : 'pt-3'}`}>
        {group.options.map((opt) => {
          const state = getActiveState(group.type, opt.filterValue)
          const config = GRID_TILE_CONFIG[opt.filterValue]
          const isActive = state === 'include'
          const isExcluded = state === 'exclude'

          return (
            <button
              key={opt.filterValue}
              onClick={() => onInclude(group, opt)}
              onContextMenu={(e) => onExclude(e, group, opt)}
              title={`${opt.label} — right-click to exclude`}
              className={`flex flex-col items-center gap-[4px] py-2.5 px-1.5 rounded-lg border-[1.5px] transition-all select-none ${
                isActive
                  ? 'border-primary text-foreground'
                  : isExcluded
                    ? 'border-destructive/50 text-destructive opacity-80'
                    : 'border-border text-muted-foreground hover:border-border/80 hover:text-foreground'
              }`}
              style={{
                background: isActive
                  ? 'hsl(var(--primary) / 0.12)'
                  : isExcluded
                    ? 'hsl(var(--destructive) / 0.08)'
                    : 'hsl(var(--secondary))',
              }}
            >
              {/* SVG preview — scaled down for compact 3-col layout */}
              <div className="transition-opacity" style={{ opacity: state ? 1 : 0.65 }}>
                {opt.filterValue === 'square' && (
                  <SquareGridSVG active={isActive} excluded={isExcluded} />
                )}
                {opt.filterValue === 'hex' && (
                  <HexGridSVG active={isActive} excluded={isExcluded} />
                )}
                {opt.filterValue === 'gridless' && (
                  <GridlessSVG active={isActive} excluded={isExcluded} />
                )}
                {opt.filterValue === 'gridded' && (
                  <AnyGridSVG active={isActive} excluded={isExcluded} />
                )}
                {opt.filterValue === 'unknown' && (
                  <UnknownGridSVG active={isActive} excluded={isExcluded} />
                )}
              </div>

              <span className="text-[11px] font-medium tracking-[0.02em] text-center leading-tight">
                {config?.label ?? opt.label}
              </span>

              {/* Status line — always takes space so tiles stay same height */}
              <span
                className={`text-[9.5px] font-semibold h-[13px] ${
                  isActive ? 'text-primary' : isExcluded ? 'text-destructive' : 'text-transparent'
                }`}
              >
                {isActive ? '✓ included' : isExcluded ? '− excluded' : '·'}
              </span>
            </button>
          )
        })}
      </div>
      {!compact && (
        <p className="px-3.5 pb-3 text-[10.5px] text-muted-foreground italic">
          Right-click a tile to exclude that grid type
        </p>
      )}
    </div>
  )
}

// ─── Grid SVGs ────────────────────────────────────────────────────────────────

function gridColor(active: boolean, excluded: boolean): string {
  if (active) return 'hsl(var(--primary))'
  if (excluded) return 'hsl(var(--destructive))'
  return 'currentColor'
}

function SquareGridSVG({ active, excluded }: { active: boolean; excluded: boolean }) {
  const c = gridColor(active, excluded)
  const op = active ? 0.7 : 0.5
  return (
    <svg width="40" height="34" viewBox="0 0 52 44" fill="none" style={{ color: c }}>
      <rect
        x="2"
        y="2"
        width="48"
        height="40"
        rx="3"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeOpacity="0.5"
      />
      <line
        x1="2"
        y1="15.3"
        x2="50"
        y2="15.3"
        stroke="currentColor"
        strokeWidth="1"
        strokeOpacity={op}
      />
      <line
        x1="2"
        y1="28.6"
        x2="50"
        y2="28.6"
        stroke="currentColor"
        strokeWidth="1"
        strokeOpacity={op}
      />
      <line
        x1="14"
        y1="2"
        x2="14"
        y2="42"
        stroke="currentColor"
        strokeWidth="1"
        strokeOpacity={op}
      />
      <line
        x1="26"
        y1="2"
        x2="26"
        y2="42"
        stroke="currentColor"
        strokeWidth="1"
        strokeOpacity={op}
      />
      <line
        x1="38"
        y1="2"
        x2="38"
        y2="42"
        stroke="currentColor"
        strokeWidth="1"
        strokeOpacity={op}
      />
    </svg>
  )
}

function HexGridSVG({ active, excluded }: { active: boolean; excluded: boolean }) {
  const c = gridColor(active, excluded)
  const op = active ? 0.8 : 0.55
  return (
    <svg width="40" height="34" viewBox="0 0 52 44" fill="none" style={{ color: c }}>
      <rect
        x="2"
        y="2"
        width="48"
        height="40"
        rx="3"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeOpacity="0.4"
      />
      <polygon
        points="16,8 22,8 25,13 22,18 16,18 13,13"
        stroke="currentColor"
        strokeWidth="1.2"
        fill="none"
        strokeOpacity={op}
      />
      <polygon
        points="25,13 31,13 34,18 31,23 25,23 22,18"
        stroke="currentColor"
        strokeWidth="1.2"
        fill="none"
        strokeOpacity={op}
      />
      <polygon
        points="16,18 22,18 25,23 22,28 16,28 13,23"
        stroke="currentColor"
        strokeWidth="1.2"
        fill="none"
        strokeOpacity={op}
      />
      <polygon
        points="25,23 31,23 34,28 31,33 25,33 22,28"
        stroke="currentColor"
        strokeWidth="1.2"
        fill="none"
        strokeOpacity={op}
      />
      <polygon
        points="34,18 40,18 43,23 40,28 34,28 31,23"
        stroke="currentColor"
        strokeWidth="1.2"
        fill="none"
        strokeOpacity={op}
      />
    </svg>
  )
}

function GridlessSVG({ active, excluded }: { active: boolean; excluded: boolean }) {
  const c = gridColor(active, excluded)
  return (
    <svg width="40" height="34" viewBox="0 0 52 44" fill="none" style={{ color: c }}>
      <rect
        x="2"
        y="2"
        width="48"
        height="40"
        rx="3"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeOpacity="0.5"
      />
      <rect
        x="10"
        y="10"
        width="32"
        height="24"
        rx="2"
        stroke="currentColor"
        strokeWidth="1"
        strokeDasharray="3 2"
        strokeOpacity="0.5"
      />
    </svg>
  )
}

function AnyGridSVG({ active, excluded }: { active: boolean; excluded: boolean }) {
  const c = gridColor(active, excluded)
  return (
    <svg width="40" height="34" viewBox="0 0 52 44" fill="none" style={{ color: c }}>
      <rect
        x="2"
        y="2"
        width="48"
        height="40"
        rx="3"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeOpacity="0.4"
      />
      <line
        x1="2"
        y1="22"
        x2="28"
        y2="22"
        stroke="currentColor"
        strokeWidth="1"
        strokeOpacity="0.5"
        strokeDasharray="2 2"
      />
      <line
        x1="14"
        y1="2"
        x2="14"
        y2="42"
        stroke="currentColor"
        strokeWidth="1"
        strokeOpacity="0.5"
        strokeDasharray="2 2"
      />
      <polygon
        points="31,12 36,10 41,13 41,19 36,22 31,19"
        stroke="currentColor"
        strokeWidth="1.2"
        fill="none"
        strokeOpacity="0.65"
      />
      <polygon
        points="31,22 36,22 39,27 36,32 31,32 28,27"
        stroke="currentColor"
        strokeWidth="1.2"
        fill="none"
        strokeOpacity="0.65"
      />
    </svg>
  )
}

function UnknownGridSVG({ active, excluded }: { active: boolean; excluded: boolean }) {
  const c = gridColor(active, excluded)
  return (
    <svg width="40" height="34" viewBox="0 0 52 44" fill="none" style={{ color: c }}>
      <rect
        x="2"
        y="2"
        width="48"
        height="40"
        rx="3"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeOpacity="0.4"
        strokeDasharray="4 2"
      />
      <text
        x="26"
        y="26"
        textAnchor="middle"
        dominantBaseline="middle"
        fontSize="16"
        fill="currentColor"
        fillOpacity="0.55"
        fontFamily="sans-serif"
      >
        ?
      </text>
    </svg>
  )
}

// ─── OptionPill ───────────────────────────────────────────────────────────────

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

// ─── ColorSwatch ──────────────────────────────────────────────────────────────

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
        title={`${label} — ${
          activeState === 'include'
            ? 'click to remove'
            : activeState === 'exclude'
              ? 'click to include'
              : 'right-click to exclude'
        }`}
        className={`aspect-square w-full rounded-full transition-all ${
          activeState === 'include'
            ? 'scale-105 ring-2 ring-primary/70'
            : activeState === 'exclude'
              ? 'ring-2 ring-destructive/50 opacity-40'
              : 'ring-1 ring-white/15 hover:ring-white/30 hover:scale-105'
        }`}
        style={{
          backgroundColor: hex,
          ...(activeState === 'include'
            ? {
                outlineStyle: 'solid',
                outlineWidth: '2px',
                outlineOffset: '2px',
                outlineColor: 'hsl(var(--primary))',
              }
            : activeState === 'exclude'
              ? {
                  outlineStyle: 'solid',
                  outlineWidth: '2px',
                  outlineOffset: '2px',
                  outlineColor: 'hsl(var(--destructive))',
                }
              : {}),
        }}
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

// ─── Custom colour picker ─────────────────────────────────────────────────────

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
      className="aspect-square w-full rounded-full border-2 border-dashed border-border/60 hover:border-foreground/50 transition-all flex items-center justify-center bg-secondary/50 hover:bg-secondary"
    >
      <Plus className="h-3.5 w-3.5 text-muted-foreground" />
      <input ref={inputRef} type="color" className="sr-only" />
    </button>
  )
}

// ─── FilterChip ───────────────────────────────────────────────────────────────

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
