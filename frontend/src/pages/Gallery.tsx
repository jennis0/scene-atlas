import { useState, useMemo, useEffect } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
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
} from 'lucide-react'
import { searchApi, groupApi, importApi } from '@/lib/api'
import { RELEVANCE_MIN, RELEVANCE_MAX, RELEVANCE_STEP, relevanceToPercent } from '@/lib/constants'
import { ImageGrid } from '@/components/ImageGrid'
import { GroupGrid } from '@/components/GroupGrid'
import { ImageViewer } from '@/components/ImageViewer'
import { ImportDialog } from '@/components/ImportDialog'
import { ActivityDock } from '@/components/ActivityDock'
import { EditGroupDialog } from '@/components/EditGroupDialog'
import { TagManagementDialog } from '@/components/TagManagementDialog'
import { MergeGroupPicker } from '@/components/MergeGroupPicker'
import { GalleryFilterPanel } from '@/components/GalleryFilterPanel'
import { FilterChipList } from '@/components/FilterMenuContent'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { SystemInfoDialog } from '@/components/SystemInfoDialog'
import { useImageGrouping } from '@/hooks/useImageGrouping'
import { useActiveImports } from '@/hooks/useActiveImports'
import { useBackgroundJobs } from '@/hooks/useBackgroundJobs'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
} from '@/components/ui/dropdown-menu'
import type { Image, ImageGroup, SearchParams, SortBy, SortDir, ViewMode } from '@/types'
import type { ActiveFilter, ImageTypeFilter } from '@/components/import/fileFilter'

// ---------------------------------------------------------------------------
// Sort options
// ---------------------------------------------------------------------------

const SORT_OPTIONS: { value: SortBy; dir: SortDir; label: string; queryOnly?: boolean }[] = [
  { value: 'created_at', dir: 'desc', label: 'Newest first' },
  { value: 'created_at', dir: 'asc', label: 'Oldest first' },
  { value: 'name', dir: 'asc', label: 'Name A\u2013Z' },
  { value: 'name', dir: 'desc', label: 'Name Z\u2013A' },
  { value: 'relevance', dir: 'desc', label: 'Relevance', queryOnly: true },
]

const DEFAULT_SORT_KEY = 'created_at:desc'

function parseSortKey(key: string): [SortBy, SortDir] {
  const [s, d] = key.split(':') as [SortBy, SortDir]
  return [s, d]
}

function loadSortKey(): string {
  const stored = localStorage.getItem('gallery-sort')
  if (stored && SORT_OPTIONS.some((o) => `${o.value}:${o.dir}` === stored)) return stored
  return DEFAULT_SORT_KEY
}

// ---------------------------------------------------------------------------
// URL ↔ filter serialisation helpers
// ---------------------------------------------------------------------------

function parseFiltersFromUrl(params: URLSearchParams): ActiveFilter[] {
  const result: ActiveFilter[] = []
  for (const val of params.getAll('tag')) {
    const label = val.includes(':') ? val.split(':').slice(1).join(':') : val
    result.push({ type: 'tag', value: val, label, exclude: false })
  }
  for (const val of params.getAll('xtag')) {
    const label = val.includes(':') ? val.split(':').slice(1).join(':') : val
    result.push({ type: 'tag', value: val, label, exclude: true })
  }
  for (const val of params.getAll('author')) {
    result.push({ type: 'author', value: val, label: val, exclude: false })
  }
  for (const val of params.getAll('xauthor')) {
    result.push({ type: 'author', value: val, label: val, exclude: true })
  }
  const gridded = params.get('gridded')
  if (gridded) {
    const displayLabel = gridded[0].toUpperCase() + gridded.slice(1)
    result.push({ type: 'gridded', value: gridded, label: `grid: ${displayLabel}`, exclude: false })
  }
  for (const val of params.getAll('color')) {
    result.push({ type: 'color', value: val, label: val, exclude: false })
  }
  for (const val of params.getAll('media_type')) {
    const label = val === 'image' ? 'Images' : val === 'video' ? 'Videos' : val
    result.push({ type: 'media_type', value: val, label: `media: ${label}`, exclude: false })
  }
  return result
}

function buildUrlParams(
  query: string,
  activeFilters: ActiveFilter[],
  imageType: ImageTypeFilter = 'all',
): URLSearchParams {
  const params = new URLSearchParams()
  if (query) params.set('q', query)
  if (imageType !== 'all') params.set('image_type', imageType)
  for (const f of activeFilters) {
    if (f.type === 'tag') params.append(f.exclude ? 'xtag' : 'tag', f.value)
    else if (f.type === 'author') params.append(f.exclude ? 'xauthor' : 'author', f.value)
    else if (f.type === 'gridded') params.set('gridded', f.value)
    else if (f.type === 'color') params.append('color', f.value)
    else if (f.type === 'media_type') params.append('media_type', f.value)
  }
  return params
}

// ---------------------------------------------------------------------------

export function Gallery() {
  const queryClient = useQueryClient()
  const [urlParams, setUrlParams] = useSearchParams()

  // UI state
  const [selectedImage, setSelectedImage] = useState<{ image: Image; index: number } | null>(null)
  const [editGroupId, setEditGroupId] = useState<number | null>(null)
  const [importReviewGroupIds, setImportReviewGroupIds] = useState<number[] | null>(null)
  const [showMassEdit, setShowMassEdit] = useState(false)
  const [viewMode, setViewMode] = useState<ViewMode>(
    () => (localStorage.getItem('gallery-view-mode') as ViewMode) || 'individual',
  )

  // Group action menu state
  const [deleteConfirmGroup, setDeleteConfirmGroup] = useState<ImageGroup | null>(null)
  const [mergeSourceGroup, setMergeSourceGroup] = useState<ImageGroup | null>(null)
  const [deleting, setDeleting] = useState(false)

  // Import state: null = closed, 'new' = fresh import, '{jobId}' = reconnect
  const [importDialogJobId, setImportDialogJobId] = useState<string | null>(null)
  const [importDialogKey, setImportDialogKey] = useState(0)
  const [showTagManagement, setShowTagManagement] = useState(false)
  const [showSystemInfo, setShowSystemInfo] = useState(false)
  const activeImports = useActiveImports()
  const backgroundJobs = useBackgroundJobs()

  // Invalidate gallery queries whenever a background import finishes
  useEffect(() => {
    return activeImports.onJobCompleted(() => {
      queryClient.invalidateQueries({ queryKey: ['images'] })
      queryClient.invalidateQueries({ queryKey: ['search'] })
      queryClient.invalidateQueries({ queryKey: ['searchFacets'] })
    })
  }, [activeImports, queryClient])

  // Search state — initialised from URL so searches are bookmarkable
  const [searchInput, setSearchInput] = useState(() => urlParams.get('q') ?? '')
  const [submittedQuery, setSubmittedQuery] = useState(() => urlParams.get('q') ?? '')
  const [filters, setFilters] = useState<ActiveFilter[]>(() => parseFiltersFromUrl(urlParams))
  const [imageType, setImageType] = useState<ImageTypeFilter>(
    () => (urlParams.get('image_type') as ImageTypeFilter) || 'all',
  )

  // Sort preference — persisted in localStorage
  const [sortKey, setSortKey] = useState(loadSortKey)
  const [sortBy, sortDir] = parseSortKey(sortKey)

  // Relevance threshold — slider value 0–0.85, applied client-side against returned scores
  const [minScore, setMinScore] = useState(() => {
    const stored = localStorage.getItem('gallery-relevance')
    return stored ? parseFloat(stored) : 0.2
  })

  // Facets — lightweight cached fetch, replaces the old 10k image fetch
  const { data: facets } = useQuery({
    queryKey: ['searchFacets'],
    queryFn: () => searchApi.facets(),
    staleTime: 60_000,
  })

  // Detect search mode from prefix
  const isSemantic = submittedQuery.startsWith('~')
  const isTextOnly = submittedQuery.startsWith('=')

  // Build search params from submitted query + active filters
  const searchParams: SearchParams = useMemo(() => {
    const params: SearchParams = { limit: 500, offset: 0 }

    if (submittedQuery) {
      if (submittedQuery.startsWith('~')) {
        params.query = submittedQuery.slice(1).trim()
        params.semantic_only = true
      } else if (submittedQuery.startsWith('=')) {
        params.query = submittedQuery.slice(1).trim()
        params.text_only = true
      } else {
        params.query = submittedQuery
      }
    }

    const includeTags = filters.filter((f) => f.type === 'tag' && !f.exclude).map((f) => f.value)
    const excludeTags = filters.filter((f) => f.type === 'tag' && f.exclude).map((f) => f.value)
    const includeAuthors = filters
      .filter((f) => f.type === 'author' && !f.exclude)
      .map((f) => f.value)
    const excludeAuthors = filters
      .filter((f) => f.type === 'author' && f.exclude)
      .map((f) => f.value)
    const griddedFilter = filters.find((f) => f.type === 'gridded')

    if (includeTags.length) params.tags = includeTags
    if (excludeTags.length) params.exclude_tags = excludeTags
    if (includeAuthors.length) params.authors = includeAuthors
    if (excludeAuthors.length) params.exclude_authors = excludeAuthors
    if (griddedFilter) {
      if (griddedFilter.value === 'square') {
        params.gridded = true
        params.grid_type = 'square'
      } else if (griddedFilter.value === 'hex') {
        params.gridded = true
        params.grid_type = 'hex'
      } else if (griddedFilter.value === 'unknown') {
        params.gridded_unknown = true
      } else {
        params.gridded = griddedFilter.value === 'gridded' ? true : false
      }
    }

    const colorFilters = filters.filter((f) => f.type === 'color').map((f) => f.value)
    if (colorFilters.length) params.colors = colorFilters

    if (imageType !== 'all') params.image_types = [imageType]

    const mediaTypeFilters = filters.filter((f) => f.type === 'media_type').map((f) => f.value)
    if (mediaTypeFilters.length) params.media_types = mediaTypeFilters

    params.sort_by = sortBy
    params.sort_dir = sortDir

    return params
  }, [submittedQuery, filters, imageType, sortBy, sortDir])

  const hasActiveSearch =
    !!searchParams.query ||
    filters.length > 0 ||
    (searchParams.tags?.length ?? 0) > 0 ||
    (searchParams.authors?.length ?? 0) > 0

  // Search query — always enabled, returns full library when no params
  const { data: searchResults, isLoading: isSearching } = useQuery({
    queryKey: ['search', searchParams],
    queryFn: () => searchApi.search(searchParams),
  })

  // Apply client-side relevance threshold when scores are available (not for text-only)
  const displayImages = useMemo(() => {
    const images = searchResults?.images ?? []
    if (!searchResults?.scores || isTextOnly) return images
    return images.filter((img) => (searchResults.scores![img.id] ?? 0) >= minScore)
  }, [searchResults, minScore, isTextOnly])

  // Show slider only when there's a scored query (not text-only, which returns no scores)
  const showRelevanceSlider = !!submittedQuery && !isTextOnly

  const totalBeforeFilter = searchResults?.images?.length ?? 0
  const filteredCount = displayImages.length

  // Group images for the grouped view
  const imageGroups = useImageGrouping({
    images: displayImages,
    scores: searchResults?.scores,
    sortBy,
    sortDir,
  })

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    setSubmittedQuery(searchInput)
    // Auto-switch to relevance sort when entering a search query
    if (searchInput.trim()) {
      setSortKey('relevance:desc')
    } else {
      // Clearing query via submit — revert to saved sort preference
      setSortKey(loadSortKey())
    }
    setUrlParams(buildUrlParams(searchInput, filters, imageType))
  }

  const handleSortChange = (newKey: string) => {
    setSortKey(newKey)
    // Persist non-relevance sorts as the user's preference
    if (newKey !== 'relevance:desc') {
      localStorage.setItem('gallery-sort', newKey)
    }
  }

  const handleFiltersChange = (newFilters: ActiveFilter[]) => {
    setFilters(newFilters)
    setUrlParams(buildUrlParams(submittedQuery, newFilters, imageType))
  }

  const handleImageTypeChange = (type: ImageTypeFilter) => {
    setImageType(type)
    setUrlParams(buildUrlParams(submittedQuery, filters, type))
  }

  const invalidateGallery = () => {
    queryClient.invalidateQueries({ queryKey: ['search'] })
    queryClient.invalidateQueries({ queryKey: ['searchFacets'] })
  }

  const handleGroupDeleteConfirm = async () => {
    if (!deleteConfirmGroup?.groupId) return
    setDeleting(true)
    try {
      await groupApi.delete(deleteConfirmGroup.groupId)
      setDeleteConfirmGroup(null)
      invalidateGallery()
    } catch (err) {
      console.error('Failed to delete group:', err)
    } finally {
      setDeleting(false)
    }
  }

  const clearAll = () => {
    setSearchInput('')
    setSubmittedQuery('')
    setFilters([])
    setImageType('all')
    setSortKey(loadSortKey())
    setUrlParams(new URLSearchParams())
  }

  const handleNext = () => {
    if (!selectedImage || selectedImage.index >= displayImages.length - 1) return
    const nextIndex = selectedImage.index + 1
    setSelectedImage({ image: displayImages[nextIndex], index: nextIndex })
  }

  const handlePrevious = () => {
    if (!selectedImage || selectedImage.index <= 0) return
    const prevIndex = selectedImage.index - 1
    setSelectedImage({ image: displayImages[prevIndex], index: prevIndex })
  }

  // Result count label suffix
  const searchModeSuffix = isSemantic ? ' · visual' : isTextOnly ? ' · keyword' : ''

  return (
    <div className="flex h-screen flex-col">
      {/* Header */}
      <header
        className="border-b border-border/70 backdrop-blur-md"
        style={{
          background:
            'linear-gradient(180deg, hsl(var(--primary) / 0.08) 0%, hsl(var(--card) / 0.97) 65%)',
        }}
      >
        <div className="container mx-auto px-4">
          {/* Title row */}
          <div className="pt-4 pb-3 flex items-start justify-between border-b border-border/70">
            <div>
              <h1 className="font-display text-2xl font-medium tracking-wide text-foreground">
                Scene Atlas
              </h1>
              <div className="mt-0.5 h-[1.5px] w-16 bg-gradient-to-r from-primary/70 to-transparent" />
            </div>
            {/* Admin cluster: utility actions (ghost) + gap + primary Import CTA */}
            <div className="flex items-center gap-1 mt-2">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setShowTagManagement(true)}
                title="Manage tag categories and values"
                className="gap-1.5 text-muted-foreground hover:text-foreground"
              >
                <Tag className="h-3.5 w-3.5" />
                Manage Tags
              </Button>
              <Button
                variant="ghost"
                size="icon"
                onClick={() => setShowSystemInfo(true)}
                title="System settings"
                className="h-8 w-8 text-muted-foreground hover:text-foreground"
              >
                <Settings className="h-4 w-4" />
              </Button>
              {/* Spacer — amber button's visual weight acts as the separator */}
              <div className="w-4 shrink-0" />
              <Button
                size="sm"
                onClick={() => {
                  setImportDialogKey((k) => k + 1)
                  setImportDialogJobId('new')
                }}
                title="Import images"
                className="gap-1.5"
              >
                <Upload className="h-3.5 w-3.5" />
                Import
              </Button>
            </div>
          </div>

          {/* Tab strip — mode selector */}
          {(() => {
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
          })()}

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
                  placeholder={`Search ${imageType === 'all' ? 'scenes' : imageType === 'battlemap' ? 'maps' : 'scenes'}…  prefix ~ for visual, = for keyword`}
                  value={searchInput}
                  onChange={(e) => setSearchInput(e.target.value)}
                  className="h-10 w-full pl-9 pr-8 rounded-r-none border-r-0 focus-visible:z-10"
                />
                {searchInput && (
                  <button
                    type="button"
                    onClick={() => {
                      setSearchInput('')
                      setSubmittedQuery('')
                      setSortKey(loadSortKey())
                      setUrlParams(buildUrlParams('', filters, imageType))
                    }}
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
                {isSearching ? 'Searching…' : 'Search'}
              </Button>
            </form>

            <GalleryFilterPanel
              filters={filters}
              facets={facets}
              onFiltersChange={handleFiltersChange}
            />

            {/* Thin separator between search tools and view controls */}
            <div className="h-5 w-px bg-border/60 shrink-0 mx-0.5" />

            {/* View mode toggle — icon buttons, no outer border */}
            <div className="flex items-center gap-0.5 shrink-0">
              <button
                onClick={() => {
                  setViewMode('individual')
                  localStorage.setItem('gallery-view-mode', 'individual')
                }}
                title="Individual images"
                className={`h-8 w-8 flex items-center justify-center rounded transition-colors
                  ${viewMode === 'individual' ? 'bg-secondary text-foreground' : 'text-muted-foreground hover:text-foreground hover:bg-secondary/50'}`}
              >
                <LayoutGrid className="h-4 w-4" />
              </button>
              <button
                onClick={() => {
                  setViewMode('grouped')
                  localStorage.setItem('gallery-view-mode', 'grouped')
                }}
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

            {/* Right cluster: count · sort · edit all · relevance */}
            <div className="flex items-center ml-auto shrink-0 text-xs text-muted-foreground gap-0">
              {/* Count */}
              {!isSearching && (
                <span className="tabular-nums">
                  {hasActiveSearch
                    ? showRelevanceSlider
                      ? `${filteredCount} / ${totalBeforeFilter} result${totalBeforeFilter !== 1 ? 's' : ''}${searchModeSuffix}`
                      : `${filteredCount} result${filteredCount !== 1 ? 's' : ''}${searchModeSuffix}`
                    : `${facets?.total_images ?? 0} scenes`}
                </span>
              )}

              {/* Sort */}
              <span className="text-border/60 px-1.5">·</span>
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

              {/* Edit all — contextual */}
              {displayImages.length > 0 && (
                <>
                  <span className="text-border/60 px-1.5">·</span>
                  <button
                    onClick={() => setShowMassEdit(true)}
                    title="Bulk-edit all scenes in current results"
                    className="flex items-center gap-1.5 hover:text-foreground transition-colors"
                  >
                    <Pencil className="h-3 w-3" />
                    Edit all ({displayImages.length})
                  </button>
                </>
              )}

              {/* Relevance slider — contextual */}
              {showRelevanceSlider && (
                <>
                  <span className="text-border/60 px-1.5">·</span>
                  <div className="flex items-center gap-2" title="Minimum relevance threshold">
                    <span>Relevance</span>
                    <input
                      type="range"
                      min={RELEVANCE_MIN}
                      max={RELEVANCE_MAX}
                      step={RELEVANCE_STEP}
                      value={minScore}
                      onChange={(e) => {
                        const val = parseFloat(e.target.value)
                        setMinScore(val)
                        localStorage.setItem('gallery-relevance', String(val))
                      }}
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

      {/* Main content */}
      <main
        className="flex-1 overflow-hidden"
        style={{ boxShadow: 'inset 0 8px 24px rgba(0,0,0,0.4)' }}
      >
        {isSearching ? (
          <div className="flex h-full items-center justify-center">
            <p className="text-muted-foreground">Searching…</p>
          </div>
        ) : displayImages.length === 0 ? (
          <div className="flex h-full items-center justify-center">
            <div className="text-center max-w-md">
              {!hasActiveSearch && (facets?.total_images ?? 0) === 0 ? (
                <>
                  <Mountain className="h-10 w-10 text-muted-foreground/30 mx-auto mb-4" />
                  <p className="text-muted-foreground mb-1">Your library is empty</p>
                  <p className="text-sm text-muted-foreground/70 mb-5">
                    Import some battlemaps and scenes to get started.
                  </p>
                  <Button
                    variant="outline"
                    size="sm"
                    className="text-primary border-primary/40 hover:bg-primary/10"
                    onClick={() => {
                      setImportDialogKey((k) => k + 1)
                      setImportDialogJobId('new')
                    }}
                  >
                    <Upload className="h-3.5 w-3.5 mr-1.5" />
                    Import
                  </Button>
                </>
              ) : (
                <>
                  <p className="text-muted-foreground mb-2">
                    {hasActiveSearch ? 'No images match your search' : 'No images available'}
                  </p>
                  {isSemantic && (
                    <p className="text-sm text-muted-foreground">
                      Try: "abandoned mine with crystals" or "winter forest temple"
                    </p>
                  )}
                  {minScore > 0 && (
                    <p className="text-sm text-muted-foreground">
                      Lower the relevance threshold to see more results.
                    </p>
                  )}
                  {hasActiveSearch && (
                    <Button variant="outline" size="sm" onClick={clearAll} className="mt-4">
                      Clear search
                    </Button>
                  )}
                </>
              )}
            </div>
          </div>
        ) : viewMode === 'individual' ? (
          <div className="h-full max-w-[1400px] mx-auto">
            <ImageGrid
              images={displayImages}
              onImageClick={(image, index) => setSelectedImage({ image, index })}
            />
          </div>
        ) : (
          <div className="h-full max-w-[1400px] mx-auto">
            <GroupGrid
              groups={imageGroups}
              onGroupClick={(group) => setSelectedImage({ image: group.heroImage, index: 0 })}
              onEditGroup={(g) => g.groupId !== null && setEditGroupId(g.groupId)}
              onDeleteGroup={(g) => setDeleteConfirmGroup(g)}
              onMergeGroup={(g) => setMergeSourceGroup(g)}
            />
          </div>
        )}
      </main>

      {/* Image viewer modal */}
      {selectedImage && (
        <ImageViewer
          image={selectedImage.image}
          onClose={() => setSelectedImage(null)}
          onNext={selectedImage.index < displayImages.length - 1 ? handleNext : undefined}
          onPrevious={selectedImage.index > 0 ? handlePrevious : undefined}
          onImageChange={(newImage) => {
            setSelectedImage((prev) => (prev ? { ...prev, image: newImage } : null))
          }}
          onEditGroup={(id) => {
            setSelectedImage(null)
            setEditGroupId(id)
          }}
          onDelete={(deletedId) => {
            const idx = selectedImage!.index
            const remaining = displayImages.filter((img) => img.id !== deletedId)
            if (remaining.length === 0) {
              setSelectedImage(null)
            } else {
              const nextIdx = Math.min(idx, remaining.length - 1)
              setSelectedImage({ image: remaining[nextIdx], index: nextIdx })
            }
          }}
        />
      )}

      {/* Edit group dialog — single group (from image viewer) */}
      <EditGroupDialog
        groupId={editGroupId}
        open={editGroupId !== null}
        onClose={() => setEditGroupId(null)}
        onSave={() => {
          setEditGroupId(null)
          invalidateGallery()
        }}
      />

      {/* Import-review dialog — opened by clicking a completed job in the tray */}
      <EditGroupDialog
        groupIds={importReviewGroupIds ?? undefined}
        open={importReviewGroupIds !== null}
        onClose={() => setImportReviewGroupIds(null)}
        onSave={() => {
          setImportReviewGroupIds(null)
          invalidateGallery()
        }}
      />

      {/* Mass-edit dialog — all images in current search results */}
      <EditGroupDialog
        seedImages={displayImages}
        open={showMassEdit}
        onClose={() => setShowMassEdit(false)}
        onSave={() => {
          setShowMassEdit(false)
          invalidateGallery()
        }}
      />

      {/* Import dialog — key forces remount so each open starts fresh */}
      <ImportDialog
        key={importDialogKey}
        open={importDialogJobId !== null}
        reconnectJobId={importDialogJobId === 'new' ? undefined : (importDialogJobId ?? undefined)}
        onOpenChange={(open) => {
          if (!open) {
            setImportDialogJobId(null)
            activeImports.refresh()
          }
        }}
        onActiveChange={() => activeImports.refresh()}
      />

      <TagManagementDialog open={showTagManagement} onClose={() => setShowTagManagement(false)} />

      <SystemInfoDialog open={showSystemInfo} onClose={() => setShowSystemInfo(false)} />

      {/* Activity dock — bottom-right floating panel showing all jobs */}
      <ActivityDock
        jobs={activeImports.jobs}
        hasActive={activeImports.hasActive}
        backgroundJobs={backgroundJobs.jobs}
        hasActiveJobs={backgroundJobs.hasActive}
        onOpenJob={(jobId) => {
          const job = activeImports.jobs.find((j) => j.jobId === jobId)
          if (job?.status === 'completed' && job.pendingGroups === 0) {
            // Truly completed with no pending groups — open EditGroupDialog
            importApi.status(jobId).then((result) => {
              const ids = result.groups
                .map((g) => g.group_id)
                .filter((id): id is number => id != null)
              if (ids.length > 0) {
                setImportReviewGroupIds(ids)
              }
            })
          } else {
            // staging, active, awaiting_input, or has pending groups — reopen ImportDialog
            setImportDialogKey((k) => k + 1)
            setImportDialogJobId(jobId)
          }
        }}
        onDismissJob={activeImports.dismissJob}
        onCancelJob={activeImports.cancelJob}
        onRefresh={activeImports.refresh}
      />

      {/* Delete group confirmation */}
      <ConfirmDialog
        open={deleteConfirmGroup !== null}
        onOpenChange={(v) => !v && setDeleteConfirmGroup(null)}
        title="Delete Group"
        description={
          <>
            Are you sure you want to delete <strong>{deleteConfirmGroup?.baseName}</strong> and all{' '}
            {deleteConfirmGroup?.totalScenes} image
            {deleteConfirmGroup?.totalScenes !== 1 ? 's' : ''}? This cannot be undone.
          </>
        }
        onConfirm={handleGroupDeleteConfirm}
        isLoading={deleting}
      />

      {/* Merge group picker */}
      <MergeGroupPicker
        open={mergeSourceGroup !== null}
        onClose={() => setMergeSourceGroup(null)}
        excludeGroupId={mergeSourceGroup?.groupId}
        currentGroupName={mergeSourceGroup?.baseName}
        onSelect={async (targetGroup) => {
          if (!mergeSourceGroup?.groupId) return
          try {
            await groupApi.merge(mergeSourceGroup.groupId, targetGroup.id)
            // Await search refetch so stale group cards are removed before
            // the picker closes and the user can interact with the gallery.
            await queryClient.refetchQueries({ queryKey: ['search'] })
            queryClient.invalidateQueries({ queryKey: ['searchFacets'] })
            setMergeSourceGroup(null)
          } catch (err) {
            console.error('Failed to merge groups:', err)
          }
        }}
      />
    </div>
  )
}
