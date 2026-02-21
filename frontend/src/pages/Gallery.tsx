import { useState, useMemo } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Search, Sparkles, X, Upload, LayoutGrid, Layers } from 'lucide-react'
import { searchApi } from '@/lib/api'
import { ImageGrid } from '@/components/ImageGrid'
import { GroupGrid } from '@/components/GroupGrid'
import { ImageViewer } from '@/components/ImageViewer'
import { ImportDialog } from '@/components/ImportDialog'
import { EditGroupDialog } from '@/components/EditGroupDialog'
import { GalleryFilterPanel } from '@/components/GalleryFilterPanel'
import { FilterChipList } from '@/components/FilterMenuContent'
import { useImageGrouping } from '@/hooks/useImageGrouping'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import type { Image, SearchParams, ViewMode } from '@/types'
import type { ActiveFilter } from '@/components/import/fileFilter'

export function Gallery() {
  const queryClient = useQueryClient()

  // UI state
  const [selectedImage, setSelectedImage] = useState<{ image: Image; index: number } | null>(null)
  const [showImport, setShowImport] = useState(false)
  const [editGroupId, setEditGroupId] = useState<number | null>(null)
  const [importActive, setImportActive] = useState(false)
  const [viewMode, setViewMode] = useState<ViewMode>('individual')

  // Search state — separate controlled input from submitted query
  const [searchInput, setSearchInput] = useState('')
  const [submittedQuery, setSubmittedQuery] = useState('')
  const [filters, setFilters] = useState<ActiveFilter[]>([])

  // Facets — lightweight cached fetch, replaces the old 10k image fetch
  const { data: facets } = useQuery({
    queryKey: ['searchFacets'],
    queryFn: () => searchApi.facets(),
    staleTime: 60_000,
  })

  // Build search params from submitted query + active filters
  const searchParams: SearchParams = useMemo(() => {
    const params: SearchParams = { limit: 500, offset: 0 }

    if (submittedQuery) {
      if (submittedQuery.startsWith('~')) {
        params.query = submittedQuery.slice(1).trim()
        params.semantic_only = true
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

  const displayImages = searchResults?.images ?? []

  // Group images for the grouped view
  const imageGroups = useImageGrouping({
    images: displayImages,
    scores: searchResults?.scores,
  })

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    setSubmittedQuery(searchInput)
  }

  const clearAll = () => {
    setSearchInput('')
    setSubmittedQuery('')
    setFilters([])
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

  const isSemantic = submittedQuery.startsWith('~')

  return (
    <div className="flex h-screen flex-col">
      {/* Header */}
      <header className="border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
        <div className="container mx-auto px-4 py-4">
          <h1 className="text-3xl font-bold mb-4">Battlemap Explorer</h1>

          {/* Search bar row */}
          <div className="flex gap-2 items-center mb-1.5">
            <form onSubmit={handleSubmit} className="relative flex-1 flex gap-2">
              <div className="relative flex-1">
                {isSemantic ? (
                  <Sparkles className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                ) : (
                  <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                )}
                <Input
                  type="text"
                  placeholder="Search battlemaps… (prefix with ~ for visual search)"
                  value={searchInput}
                  onChange={(e) => setSearchInput(e.target.value)}
                  className="pl-9"
                />
              </div>
              <Button type="submit" disabled={isSearching}>
                {isSearching ? 'Searching…' : 'Search'}
              </Button>
            </form>

            {/* Filter panel */}
            <GalleryFilterPanel
              filters={filters}
              facets={facets}
              onFiltersChange={setFilters}
            />

            {/* Clear all */}
            {hasActiveSearch && (
              <Button variant="ghost" size="icon" onClick={clearAll} title="Clear search and filters">
                <X className="h-4 w-4" />
              </Button>
            )}

            {/* Import button */}
            <Button
              variant="outline"
              size="icon"
              onClick={() => setShowImport(true)}
              title={importActive ? 'Import in progress — click to view' : 'Import images'}
              className="relative"
            >
              <Upload className="h-4 w-4" />
              {importActive && (
                <span className="absolute -top-1 -right-1 h-3 w-3 rounded-full bg-primary animate-pulse" />
              )}
            </Button>

            {/* View toggle */}
            <div className="flex gap-1">
              <Button
                variant={viewMode === 'individual' ? 'default' : 'outline'}
                size="icon"
                onClick={() => setViewMode('individual')}
                title="Individual images"
              >
                <LayoutGrid className="h-4 w-4" />
              </Button>
              <Button
                variant={viewMode === 'grouped' ? 'default' : 'outline'}
                size="icon"
                onClick={() => setViewMode('grouped')}
                title="Variant groups"
              >
                <Layers className="h-4 w-4" />
              </Button>
            </div>
          </div>

          {/* Active filter chips — always-reserved row so adding chips never shifts layout */}
          <div className="min-h-[26px] flex items-center">
            <FilterChipList filters={filters} onFiltersChange={setFilters} />
          </div>

          {/* Result count + hint */}
          {!isSearching && (
            <div className="text-xs text-muted-foreground">
              {hasActiveSearch
                ? `${searchResults?.total ?? 0} result${(searchResults?.total ?? 0) !== 1 ? 's' : ''}`
                : `${facets?.total_images ?? 0} battlemaps`}
              {isSemantic && ' · visual search'}
            </div>
          )}
        </div>
      </header>

      {/* Main content */}
      <main className="flex-1 overflow-hidden">
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
              {hasActiveSearch && (
                <Button variant="outline" size="sm" onClick={clearAll} className="mt-4">
                  Clear search
                </Button>
              )}
            </div>
          </div>
        ) : viewMode === 'individual' ? (
          <ImageGrid
            images={displayImages}
            onImageClick={(image, index) => setSelectedImage({ image, index })}
          />
        ) : (
          <GroupGrid
            groups={imageGroups}
            onGroupClick={(group) => setSelectedImage({ image: group.heroImage, index: 0 })}
          />
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

      {/* Edit group dialog */}
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

      {/* Import dialog */}
      <ImportDialog
        open={showImport}
        onOpenChange={setShowImport}
        onActiveChange={setImportActive}
      />
    </div>
  )
}
