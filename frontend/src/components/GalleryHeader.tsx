import { useMemo } from 'react'
import {
  Search,
  Sparkles,
  X,
  Upload,
  LayoutGrid,
  Layers,
  Pencil,
  AlignLeft,
  Tag,
  Settings,
  ArrowUpDown,
  Compass,
  Map,
  Mountain,
  Sun,
  Moon,
  Loader2,
} from 'lucide-react'
import { GalleryFilterPanel } from '@/components/GalleryFilterPanel'
import { FilterChipList } from '@/components/FilterMenuContent'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
} from '@/components/ui/dropdown-menu'
import { useTheme } from '@/contexts/ThemeContext'
import { isApp } from '@/lib/appMode'
import {
  RELEVANCE_MIN,
  RELEVANCE_MAX,
  RELEVANCE_STEP,
  relevanceToPercent,
  MAX_SEARCH_LENGTH,
} from '@/lib/constants'
import { SORT_OPTIONS } from '@/hooks/useGallerySearch'
import type { UseGallerySearchReturn } from '@/hooks/useGallerySearch'
import type { ImageTypeFilter } from '@/components/import/fileFilter'

// ---------------------------------------------------------------------------
// Platform helpers for borderless window layout
// ---------------------------------------------------------------------------

const isMac = isApp && window.electronAPI?.platform === 'darwin'
const needsOverlayPadding = isApp && !isMac // Windows/Linux titlebar overlay

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface GalleryHeaderProps {
  search: UseGallerySearchReturn & {
    editAllLoading?: boolean
  }
  onOpenImport: () => void
  onOpenTagManagement: () => void
  onOpenSystemInfo: () => void
  onOpenMassEdit: () => void
  displayImageCount: number
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function GalleryHeader({
  search,
  onOpenImport,
  onOpenTagManagement,
  onOpenSystemInfo,
  onOpenMassEdit,
  displayImageCount,
}: GalleryHeaderProps) {
  const { theme, toggleTheme } = useTheme()
  const {
    searchInput,
    setSearchInput,
    submittedQuery,
    filters,
    imageType,
    sortKey,
    minScore,
    setMinScore,
    viewMode,
    setViewMode,
    isSemantic,
    isTextOnly,
    hasActiveSearch,
    searchModeSuffix,
    showRelevanceSlider,
    totalBeforeFilter,
    filteredCount,
    totalGroups,
    facets,
    isSearching,
    handleSubmit,
    handleSortChange,
    handleFiltersChange,
    handleImageTypeChange,
    clearAll,
  } = search

  // Tab strip -- memoised so it only recalculates when facets or selection change
  const tabStrip = useMemo(() => {
    const typeCounts = Object.fromEntries(
      (facets?.image_types ?? []).map((t) => [t.value, t.count]),
    )
    const total = Object.values(typeCounts).reduce((s, n) => s + n, 0)
    const tabs = [
      { value: 'all' as ImageTypeFilter, label: 'All', Icon: Compass, count: total },
      {
        value: 'battlemap' as ImageTypeFilter,
        label: 'Maps',
        Icon: Map,
        count: typeCounts['battlemap'] ?? 0,
      },
      {
        value: 'scene' as ImageTypeFilter,
        label: 'Scenes',
        Icon: Mountain,
        count: typeCounts['scene'] ?? 0,
      },
    ]
    return (
      <div className="-mx-4 px-4 flex items-stretch border-b border-border/60">
        {tabs.map(({ value, label, Icon, count }) => (
          <button
            key={value}
            onClick={() => handleImageTypeChange(value)}
            className={`flex items-center gap-2 py-2.5 pr-4 mr-1 text-sm font-medium border-b-2 transition-colors
              ${
                imageType === value
                  ? 'border-primary text-foreground'
                  : 'border-transparent text-muted-foreground hover:text-foreground'
              }`}
          >
            <Icon className="h-3.5 w-3.5 shrink-0" />
            {label}
            {count > 0 && (
              <span
                className={`text-[10px] font-normal px-1.5 py-px rounded-full transition-colors
                ${
                  imageType === value
                    ? 'bg-primary/15 text-primary'
                    : 'bg-secondary text-muted-foreground'
                }`}
              >
                {count.toLocaleString()}
              </span>
            )}
          </button>
        ))}
      </div>
    )
  }, [facets, imageType, handleImageTypeChange])

  return (
    <header
      className="border-b border-border/70 backdrop-blur-md"
      style={{
        background:
          'linear-gradient(180deg, hsl(var(--primary) / 0.08) 0%, hsl(var(--card) / 0.97) 65%)',
      }}
    >
      {/* Windows/Linux: draggable titlebar strip matching the OS overlay zone */}
      {needsOverlayPadding && <div className="h-8 drag-region" />}
      <div className={`container mx-auto px-4 ${isMac ? 'pl-20' : ''}`}>
        {/* Title row */}
        <div
          className={`${needsOverlayPadding ? 'pt-2 pb-2' : 'pt-4 pb-3'} flex ${needsOverlayPadding ? 'items-center' : 'items-start'} justify-between border-b border-border/70 ${isApp ? 'drag-region' : ''}`}
        >
          <div>
            <h1 className="font-display text-2xl font-medium tracking-wide text-foreground">
              Scene Atlas
            </h1>
            <div className="mt-0.5 h-[1.5px] w-16 bg-gradient-to-r from-primary/70 to-transparent" />
          </div>
          {/* Admin cluster: utility actions (ghost) + gap + primary Import CTA */}
          <div
            className={`flex items-center gap-1 ${needsOverlayPadding ? '' : 'mt-2'} ${isApp ? 'no-drag-region' : ''}`}
          >
            <Button
              variant="ghost"
              size="sm"
              onClick={onOpenTagManagement}
              title="Manage tag categories and values"
              className="gap-1.5 text-muted-foreground hover:text-foreground"
            >
              <Tag className="h-3.5 w-3.5" />
              Manage Tags
            </Button>
            <Button
              variant="ghost"
              size="icon"
              onClick={onOpenSystemInfo}
              title="Library information"
              className="h-8 w-8 text-muted-foreground hover:text-foreground"
            >
              <Settings className="h-4 w-4" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              onClick={toggleTheme}
              title={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
              className="h-8 w-8 text-muted-foreground hover:text-foreground"
            >
              {theme === 'dark' ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
            </Button>
            {/* Spacer */}
            <div className="w-4 shrink-0" />
            <Button size="sm" onClick={onOpenImport} title="Import images" className="gap-1.5">
              <Upload className="h-3.5 w-3.5" />
              Import
            </Button>
          </div>
        </div>

        {/* Tab strip -- mode selector */}
        {tabStrip}

        {/* Search + controls row */}
        <div className="flex items-center gap-2 pt-3 pb-3">
          <form onSubmit={handleSubmit} className="flex flex-1 min-w-0">
            {/* Input with inline clear button */}
            <div className="relative flex-1 min-w-0">
              {isSemantic ? (
                <Sparkles className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground pointer-events-none" />
              ) : isTextOnly ? (
                <AlignLeft className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground pointer-events-none" />
              ) : (
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground pointer-events-none" />
              )}
              <Input
                type="text"
                placeholder={`Search ${imageType === 'all' ? 'scenes' : imageType === 'battlemap' ? 'maps' : 'scenes'}\u2026  "quotes" for exact phrase, ~ visual, = keyword`}
                value={searchInput}
                onChange={(e) => setSearchInput(e.target.value)}
                maxLength={MAX_SEARCH_LENGTH}
                className="h-10 w-full pl-9 pr-8 rounded-r-none border-r-0 focus-visible:z-10"
              />
              {searchInput && (
                <button
                  type="button"
                  onClick={search.clearSearch}
                  tabIndex={-1}
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              )}
            </div>

            <Button
              type="submit"
              disabled={isSearching}
              className="rounded-l-none h-10 shrink-0 px-5"
            >
              {isSearching ? 'Searching\u2026' : 'Search'}
            </Button>
          </form>

          <GalleryFilterPanel
            filters={filters}
            facets={facets}
            onFiltersChange={handleFiltersChange}
          />

          {/* Thin separator between search tools and view controls */}
          <div className="h-5 w-px bg-border/60 shrink-0 mx-0.5" />

          {/* View mode toggle -- icon buttons, no outer border */}
          <div className="flex items-center gap-0.5 shrink-0">
            <button
              onClick={() => setViewMode('individual')}
              title="Individual images"
              className={`h-8 w-8 flex items-center justify-center rounded transition-colors
                ${viewMode === 'individual' ? 'bg-secondary text-foreground' : 'text-muted-foreground hover:text-foreground hover:bg-secondary/50'}`}
            >
              <LayoutGrid className="h-4 w-4" />
            </button>
            <button
              onClick={() => setViewMode('grouped')}
              title="Groups"
              className={`h-8 w-8 flex items-center justify-center rounded transition-colors
                ${viewMode === 'grouped' ? 'bg-secondary text-foreground' : 'text-muted-foreground hover:text-foreground hover:bg-secondary/50'}`}
            >
              <Layers className="h-4 w-4" />
            </button>
          </div>
        </div>

        {/* Chips + status row */}
        <div className="flex items-center pb-4 min-h-[32px]">
          {/* Filter chips + clear all */}
          <div className="flex-1 min-w-0 flex items-center gap-1.5 flex-wrap">
            <FilterChipList filters={filters} onFiltersChange={handleFiltersChange} />
            {hasActiveSearch && (
              <button
                onClick={clearAll}
                className="text-xs text-muted-foreground hover:text-foreground transition-colors flex items-center gap-1 ml-1"
              >
                <X className="h-2.5 w-2.5" />
                Clear all
              </button>
            )}
          </div>

          {/* Right cluster: count + sort + edit all + relevance */}
          <div className="flex items-center ml-auto shrink-0 text-xs text-muted-foreground gap-0">
            {/* Count */}
            {!isSearching && (
              <span className="tabular-nums">
                {viewMode === 'grouped'
                  ? `${totalGroups} group${totalGroups !== 1 ? 's' : ''}`
                  : hasActiveSearch
                    ? showRelevanceSlider
                      ? `${filteredCount} / ${totalBeforeFilter} result${totalBeforeFilter !== 1 ? 's' : ''}${searchModeSuffix}`
                      : `${filteredCount} result${filteredCount !== 1 ? 's' : ''}${searchModeSuffix}`
                    : `${facets?.total_images ?? 0} scenes`}
              </span>
            )}

            {/* Sort */}
            <span className="text-border/60 px-1.5">&middot;</span>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button className="flex items-center gap-1 hover:text-foreground transition-colors">
                  {SORT_OPTIONS.find((o) => `${o.value}:${o.dir}` === sortKey)?.label ?? 'Sort'}
                  <ArrowUpDown className="h-2.5 w-2.5 opacity-50" />
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-40">
                <DropdownMenuRadioGroup value={sortKey} onValueChange={handleSortChange}>
                  {SORT_OPTIONS.map((opt) => {
                    const key = `${opt.value}:${opt.dir}`
                    return (
                      <DropdownMenuRadioItem
                        key={key}
                        value={key}
                        disabled={opt.queryOnly && !submittedQuery}
                      >
                        {opt.label}
                      </DropdownMenuRadioItem>
                    )
                  })}
                </DropdownMenuRadioGroup>
              </DropdownMenuContent>
            </DropdownMenu>

            {/* Edit all -- contextual */}
            {viewMode === 'grouped'
              ? totalGroups > 0 && (
                  <>
                    <span className="text-border/60 px-1.5">&middot;</span>
                    {totalGroups > 500 ? (
                      <div
                        title={`Too many groups (${totalGroups}) — apply filters to narrow below 500`}
                        className="flex items-center gap-1.5 cursor-not-allowed opacity-50"
                      >
                        <Pencil className="h-3 w-3" />
                        Edit all ({totalGroups})
                      </div>
                    ) : (
                      <button
                        onClick={onOpenMassEdit}
                        disabled={search.editAllLoading}
                        title={
                          search.editAllLoading
                            ? 'Loading images...'
                            : 'Bulk-edit all groups in current results'
                        }
                        className="flex items-center gap-1.5 hover:text-foreground transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                      >
                        {search.editAllLoading ? (
                          <Loader2 className="h-3 w-3 animate-spin" />
                        ) : (
                          <Pencil className="h-3 w-3" />
                        )}
                        Edit all ({totalGroups})
                      </button>
                    )}
                  </>
                )
              : displayImageCount > 0 && (
                  <>
                    <span className="text-border/60 px-1.5">&middot;</span>
                    <button
                      onClick={onOpenMassEdit}
                      title="Bulk-edit all scenes in current results"
                      className="flex items-center gap-1.5 hover:text-foreground transition-colors"
                    >
                      <Pencil className="h-3 w-3" />
                      Edit all ({displayImageCount})
                    </button>
                  </>
                )}

            {/* Relevance slider -- contextual */}
            {showRelevanceSlider && (
              <>
                <span className="text-border/60 px-1.5">&middot;</span>
                <div className="flex items-center gap-2" title="Minimum relevance threshold">
                  <span>Relevance</span>
                  <input
                    type="range"
                    min={RELEVANCE_MIN}
                    max={RELEVANCE_MAX}
                    step={RELEVANCE_STEP}
                    value={minScore}
                    onChange={(e) => setMinScore(parseFloat(e.target.value))}
                    className="w-20 cursor-pointer accent-primary"
                    style={{ height: '4px' }}
                  />
                  <span className="tabular-nums w-7 text-right">
                    {minScore > 0 ? `${relevanceToPercent(minScore)}%` : 'All'}
                  </span>
                </div>
              </>
            )}
          </div>
        </div>
      </div>
    </header>
  )
}
