import { useState, useMemo } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Search, Sparkles, X, Upload, LayoutGrid, Layers, Pencil, AlignLeft, Tag } from 'lucide-react'
import { searchApi } from '@/lib/api'
import { ImageGrid } from '@/components/ImageGrid'
import { GroupGrid } from '@/components/GroupGrid'
import { ImageViewer } from '@/components/ImageViewer'
import { ImportDialog } from '@/components/ImportDialog'
import { ImportTray } from '@/components/ImportTray'
import { EditGroupDialog } from '@/components/EditGroupDialog'
import { TagManagementDialog } from '@/components/TagManagementDialog'
import { GalleryFilterPanel } from '@/components/GalleryFilterPanel'
import { FilterChipList } from '@/components/FilterMenuContent'
import { useImageGrouping } from '@/hooks/useImageGrouping'
import { useActiveImports } from '@/hooks/useActiveImports'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import type { Image, SearchParams, ViewMode } from '@/types'
import type { ActiveFilter } from '@/components/import/fileFilter'

export function Gallery() {
  const queryClient = useQueryClient()

  // UI state
  const [selectedImage, setSelectedImage] = useState<{ image: Image; index: number } | null>(null)
  const [editGroupId, setEditGroupId] = useState<number | null>(null)
  const [showMassEdit, setShowMassEdit] = useState(false)
  const [viewMode, setViewMode] = useState<ViewMode>('individual')

  // Import state: null = closed, 'new' = fresh import, '{jobId}' = reconnect
  const [importDialogJobId, setImportDialogJobId] = useState<string | null>(null)
  const [showTagManagement, setShowTagManagement] = useState(false)
  const activeImports = useActiveImports()

  // Search state — separate controlled input from submitted query
  const [searchInput, setSearchInput] = useState('')
  const [submittedQuery, setSubmittedQuery] = useState('')
  const [filters, setFilters] = useState<ActiveFilter[]>([])

  // Relevance threshold — slider value 0–0.85, applied client-side against returned scores
  const [minScore, setMinScore] = useState(0.2)

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
    const includeAuthors = filters.filter((f) => f.type === 'author' && !f.exclude).map((f) => f.value)
    const excludeAuthors = filters.filter((f) => f.type === 'author' && f.exclude).map((f) => f.value)
    const griddedFilter = filters.find((f) => f.type === 'gridded')

    if (includeTags.length) params.tags = includeTags
    if (excludeTags.length) params.exclude_tags = excludeTags
    if (includeAuthors.length) params.authors = includeAuthors
    if (excludeAuthors.length) params.exclude_authors = excludeAuthors
    if (griddedFilter) {
      params.gridded =
        griddedFilter.value === 'gridded' ? true
        : griddedFilter.value === 'gridless' ? false
        : undefined
    }

    return params
  }, [submittedQuery, filters])

  const hasActiveSearch = !!searchParams.query || filters.length > 0 ||
    (searchParams.tags?.length ?? 0) > 0 || (searchParams.authors?.length ?? 0) > 0

  // Search query — always enabled, returns full library when no params
  const { data: searchResults, isLoading: isSearching } = useQuery({
    queryKey: ['search', searchParams],
    queryFn: () => searchApi.search(searchParams),
  })

  // Apply client-side relevance threshold when scores are available
  const displayImages = useMemo(() => {
    const images = searchResults?.images ?? []
    if (!searchResults?.scores) return images
    return images.filter((img) => (searchResults.scores![img.id] ?? 0) >= minScore)
  }, [searchResults, minScore])

  // Show slider only when there's a scored query (not text-only, which returns no scores)
  const showRelevanceSlider = !!submittedQuery && !isTextOnly

  const totalBeforeFilter = searchResults?.images?.length ?? 0
  const filteredCount = displayImages.length

  // Group images for the grouped view
  const imageGroups = useImageGrouping({
    images: displayImages,
    scores: searchResults?.scores,
  })

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    setSubmittedQuery(searchInput)
    setMinScore(0.2) // reset threshold on new search
  }

  const clearAll = () => {
    setSearchInput('')
    setSubmittedQuery('')
    setFilters([])
    setMinScore(0.2)
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
          background: 'linear-gradient(180deg, hsl(38 60% 58% / 0.08) 0%, hsl(222 22% 12% / 0.97) 65%)',
        }}
      >
        <div className="container mx-auto px-4">

          {/* Title row */}
          <div className="pt-8 pb-4 flex items-start justify-between">
            <div>
              <h1 className="font-display text-4xl font-semibold tracking-wide text-foreground">
                Library of Worlds
              </h1>
              <div className="mt-3 h-[2px] w-24 rounded-full bg-primary/50" />
            </div>
            <div className="flex items-center gap-2 mt-1">
              {displayImages.length > 0 && (
                <Button
                  variant="outline"
                  onClick={() => setShowMassEdit(true)}
                  className="gap-2"
                  title="Bulk-edit all maps in current results"
                >
                  <Pencil className="h-4 w-4" />
                  Edit Results
                  <span className="text-muted-foreground text-xs">({displayImages.length})</span>
                </Button>
              )}
              <Button
                variant="outline"
                onClick={() => setShowTagManagement(true)}
                title="Manage tag categories and values"
                className="gap-2"
              >
                <Tag className="h-4 w-4" />
                Tags
              </Button>
              <Button
                variant="outline"
                onClick={() => setImportDialogJobId('new')}
                title="Import images"
                className="gap-2"
              >
                <Upload className="h-4 w-4" />
                Import
              </Button>
            </div>
          </div>

          {/* Search + tools row */}
          <div className="flex items-center gap-3 pb-5">
            <form onSubmit={handleSubmit} className="flex-1 flex gap-2 min-w-0">
              <div className="relative flex-1 min-w-0">
                {isSemantic ? (
                  <Sparkles className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                ) : isTextOnly ? (
                  <AlignLeft className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                ) : (
                  <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                )}
                <Input
                  type="text"
                  placeholder="Search worlds…  ~ visual  ·  = keyword"
                  value={searchInput}
                  onChange={(e) => setSearchInput(e.target.value)}
                  className="pl-9 w-full"
                />
              </div>
              <Button type="submit" disabled={isSearching} variant="secondary">
                {isSearching ? 'Searching…' : 'Search'}
              </Button>
            </form>

            <GalleryFilterPanel
              filters={filters}
              facets={facets}
              onFiltersChange={setFilters}
            />
            {hasActiveSearch && (
              <Button variant="ghost" size="icon" onClick={clearAll} title="Clear search and filters">
                <X className="h-4 w-4" />
              </Button>
            )}

            {/* Segmented view toggle */}
            <div className="flex rounded-md overflow-hidden border border-border shrink-0">
              <button
                onClick={() => setViewMode('individual')}
                title="Individual images"
                className={`h-10 w-10 flex items-center justify-center border-r border-border transition-colors
                  ${viewMode === 'individual' ? 'bg-secondary text-foreground' : 'text-foreground/50 hover:text-foreground hover:bg-secondary/50'}`}
              >
                <LayoutGrid className="h-4 w-4" />
              </button>
              <button
                onClick={() => setViewMode('grouped')}
                title="Variant groups"
                className={`h-10 w-10 flex items-center justify-center transition-colors
                  ${viewMode === 'grouped' ? 'bg-secondary text-foreground' : 'text-foreground/50 hover:text-foreground hover:bg-secondary/50'}`}
              >
                <Layers className="h-4 w-4" />
              </button>
            </div>
          </div>

          {/* Chips + count row */}
          <div className="flex items-center gap-3 pb-4 min-h-[28px]">
            <FilterChipList filters={filters} onFiltersChange={setFilters} />
            {showRelevanceSlider && (
              <div
                className="flex items-center gap-2 ml-auto shrink-0"
                title="Minimum relevance threshold"
              >
                <span className="text-xs text-muted-foreground">Relevance</span>
                <input
                  type="range"
                  min="0.1"
                  max="0.5"
                  step="0.01"
                  value={minScore}
                  onChange={(e) => setMinScore(parseFloat(e.target.value))}
                  className="w-24 cursor-pointer accent-primary"
                  style={{ height: '4px' }}
                />
                <span className="text-xs text-muted-foreground tabular-nums w-8 text-right">
                  {minScore > 0 ? `${Math.round((minScore / 0.4 - 0.25) * 100)}%` : 'All'}
                </span>
              </div>
            )}
            {!isSearching && (
              <span className={`text-xs text-muted-foreground tabular-nums shrink-0 ${showRelevanceSlider ? '' : 'ml-auto'}`}>
                {hasActiveSearch ? (
                  showRelevanceSlider ? (
                    <>
                      <span
                        style={{ display: 'inline-block', minWidth: `${String(totalBeforeFilter).length}ch`, textAlign: 'right' }}
                      >{filteredCount}</span>
                      {` / ${totalBeforeFilter} result${totalBeforeFilter !== 1 ? 's' : ''}${searchModeSuffix}`}
                    </>
                  ) : (
                    `${filteredCount} result${filteredCount !== 1 ? 's' : ''}${searchModeSuffix}`
                  )
                ) : `${facets?.total_images ?? 0} worlds`}
              </span>
            )}
          </div>

        </div>
      </header>

      {/* Main content */}
      <main className="flex-1 overflow-hidden" style={{ boxShadow: 'inset 0 8px 24px rgba(0,0,0,0.4)' }}>
        {isSearching ? (
          <div className="flex h-full items-center justify-center">
            <p className="text-muted-foreground">Searching…</p>
          </div>
        ) : displayImages.length === 0 ? (
          <div className="flex h-full items-center justify-center">
            <div className="text-center max-w-md">
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
            setSelectedImage((prev) => prev ? { ...prev, image: newImage } : null)
          }}
          onEditGroup={(id) => { setSelectedImage(null); setEditGroupId(id) }}
        />
      )}

      {/* Edit group dialog — single group (from image viewer) */}
      <EditGroupDialog
        groupId={editGroupId}
        open={editGroupId !== null}
        onClose={() => setEditGroupId(null)}
        onSave={() => {
          setEditGroupId(null)
          queryClient.invalidateQueries({ queryKey: ['search'] })
          queryClient.invalidateQueries({ queryKey: ['searchFacets'] })
        }}
      />

      {/* Mass-edit dialog — all images in current search results */}
      <EditGroupDialog
        seedImages={displayImages}
        open={showMassEdit}
        onClose={() => setShowMassEdit(false)}
        onSave={() => {
          setShowMassEdit(false)
          queryClient.invalidateQueries({ queryKey: ['search'] })
          queryClient.invalidateQueries({ queryKey: ['searchFacets'] })
        }}
      />

      {/* Import dialog */}
      <ImportDialog
        open={importDialogJobId !== null}
        reconnectJobId={importDialogJobId === 'new' ? undefined : importDialogJobId ?? undefined}
        onOpenChange={(open) => {
          if (!open) {
            setImportDialogJobId(null)
            activeImports.refresh()
          }
        }}
      />

      <TagManagementDialog
        open={showTagManagement}
        onClose={() => setShowTagManagement(false)}
      />

      {/* Import tray — right-side overlay showing active imports */}
      <ImportTray
        jobs={activeImports.jobs}
        hasActive={activeImports.hasActive}
        onOpenJob={(jobId) => setImportDialogJobId(jobId)}
        onDismissJob={activeImports.dismissJob}
        onRefresh={activeImports.refresh}
      />
    </div>
  )
}
