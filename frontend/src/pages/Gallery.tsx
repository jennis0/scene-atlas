import { useState, useEffect, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Search, Sparkles, Filter, X, Upload, LayoutGrid, Layers } from 'lucide-react'
import { imageApi, searchApi, tagApi } from '@/lib/api'
import { ImageGrid } from '@/components/ImageGrid'
import { GroupGrid } from '@/components/GroupGrid'
import { ImageViewer } from '@/components/ImageViewer'
import { ImportDialog } from '@/components/ImportDialog'
import { useImageGrouping } from '@/hooks/useImageGrouping'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from '@/components/ui/sheet'
import type { Image, SearchParams, ViewMode } from '@/types'

type SearchMode = 'text' | 'semantic'

export function Gallery() {
  const [selectedImage, setSelectedImage] = useState<{ image: Image; index: number } | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [searchMode, setSearchMode] = useState<SearchMode>('text')
  const [selectedAuthors, setSelectedAuthors] = useState<string[]>([])
  const [selectedTags, setSelectedTags] = useState<string[]>([])
  const [showFilters, setShowFilters] = useState(false)
  const [showImport, setShowImport] = useState(false)
  const [importActive, setImportActive] = useState(false)
  const [filterSearch, setFilterSearch] = useState('')
  const [viewMode, setViewMode] = useState<ViewMode>('individual')

  // Fetch all images for deriving authors
  const { data: allImages = [], isLoading: isLoadingImages } = useQuery({
    queryKey: ['images'],
    queryFn: () => imageApi.list(10000, 0),
  })

  // Fetch tag stats for filter options
  const { data: tagStats } = useQuery({
    queryKey: ['tagStats'],
    queryFn: () => tagApi.getStats(),
  })

  // Derive unique authors from images
  const availableAuthors = useMemo(() => {
    const authors = new Set(allImages.map((img) => img.author))
    return Array.from(authors).sort()
  }, [allImages])

  // Get available tag values organized by category
  const availableTagsByCategory = useMemo(() => {
    if (!tagStats?.categories) return {}

    const tagsByCategory: Record<string, string[]> = {}

    // Iterate over category names from tagStats
    Object.keys(tagStats.categories).forEach((categoryName) => {
      // Derive tag values from images for this category
      const tags = new Set<string>()
      allImages.forEach((img) => {
        img.tags?.forEach((tag) => {
          if (tag.category === categoryName) {
            tags.add(tag.value)
          }
        })
      })
      if (tags.size > 0) {
        tagsByCategory[categoryName] = Array.from(tags).sort()
      }
    })

    return tagsByCategory
  }, [tagStats, allImages])

  // Filter authors and tags based on filter search
  const filteredAuthors = useMemo(() => {
    if (!filterSearch) return availableAuthors
    const search = filterSearch.toLowerCase()
    return availableAuthors.filter((author) => author.toLowerCase().includes(search))
  }, [availableAuthors, filterSearch])

  const filteredTagsByCategory = useMemo(() => {
    if (!filterSearch) return availableTagsByCategory
    const search = filterSearch.toLowerCase()
    const filtered: Record<string, string[]> = {}

    Object.entries(availableTagsByCategory).forEach(([category, values]) => {
      // Include category if name matches or any value matches
      const categoryMatches = category.toLowerCase().includes(search)
      const matchingValues = values.filter((value) => value.toLowerCase().includes(search))

      if (categoryMatches || matchingValues.length > 0) {
        filtered[category] = categoryMatches ? values : matchingValues
      }
    })

    return filtered
  }, [availableTagsByCategory, filterSearch])

  // Build search params
  const searchParams: SearchParams = useMemo(() => {
    const params: SearchParams = {
      limit: 1000,
      offset: 0,
    }

    if (searchMode === 'text' && searchQuery) {
      params.text = searchQuery
    } else if (searchMode === 'semantic' && searchQuery) {
      params.semantic = searchQuery
    }

    if (selectedAuthors.length > 0) {
      params.authors = selectedAuthors // Multiple authors with OR logic
    }

    if (selectedTags.length > 0) {
      params.tags = selectedTags // OR within category, AND across categories
    }

    return params
  }, [searchMode, searchQuery, selectedAuthors, selectedTags])

  // Perform search with filters
  const { data: searchResults, isLoading: isSearching, refetch } = useQuery({
    queryKey: ['search', searchParams],
    queryFn: () => searchApi.search(searchParams),
    enabled: false, // Manual trigger
  })

  // Trigger search when params change (but not for semantic search queries)
  useEffect(() => {
    // Only auto-trigger for text search or filters, not semantic search
    if (searchMode === 'text' || selectedAuthors.length > 0 || selectedTags.length > 0) {
      if (searchQuery || selectedAuthors.length > 0 || selectedTags.length > 0) {
        refetch()
      }
    }
  }, [searchParams, refetch, searchMode, searchQuery, selectedAuthors.length, selectedTags.length])

  const handleSemanticSearch = (e: React.FormEvent) => {
    e.preventDefault()
    if (searchQuery.trim() && searchMode === 'semantic') {
      refetch()
    }
  }

  // Determine which images to display
  const filteredImages = useMemo(() => {
    if (searchQuery || selectedAuthors.length > 0 || selectedTags.length > 0) {
      return searchResults?.images || []
    }
    return allImages
  }, [searchQuery, selectedAuthors, selectedTags, searchResults, allImages])

  // Group images for the grouped view
  const imageGroups = useImageGrouping({
    images: filteredImages,
    allImages,
    scores: searchResults?.scores,
  })

  const handleSearchModeChange = (mode: SearchMode) => {
    setSearchMode(mode)
  }

  const toggleAuthor = (author: string) => {
    setSelectedAuthors((prev) =>
      prev.includes(author) ? prev.filter((a) => a !== author) : [...prev, author]
    )
  }

  const toggleTag = (category: string, value: string) => {
    const tagFilter = `${category}:${value}`
    setSelectedTags((prev) =>
      prev.includes(tagFilter) ? prev.filter((t) => t !== tagFilter) : [...prev, tagFilter]
    )
  }

  const clearFilters = () => {
    setSelectedAuthors([])
    setSelectedTags([])
    setSearchQuery('')
  }

  const hasActiveFilters = selectedAuthors.length > 0 || selectedTags.length > 0 || searchQuery.length > 0

  const handleNext = () => {
    if (!selectedImage || selectedImage.index >= filteredImages.length - 1) return
    const nextIndex = selectedImage.index + 1
    setSelectedImage({ image: filteredImages[nextIndex], index: nextIndex })
  }

  const handlePrevious = () => {
    if (!selectedImage || selectedImage.index <= 0) return
    const prevIndex = selectedImage.index - 1
    setSelectedImage({ image: filteredImages[prevIndex], index: prevIndex })
  }

  return (
    <div className="flex h-screen flex-col">
      {/* Header */}
      <header className="border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
        <div className="container mx-auto px-4 py-4">
          <h1 className="text-3xl font-bold mb-4">Battlemap Explorer</h1>

          {/* Search mode toggle + view mode toggle */}
          <div className="flex gap-2 mb-3">
            <Button
              variant={searchMode === 'text' ? 'default' : 'outline'}
              size="sm"
              onClick={() => handleSearchModeChange('text')}
            >
              <Search className="h-4 w-4 mr-2" />
              Text Search
            </Button>
            <Button
              variant={searchMode === 'semantic' ? 'default' : 'outline'}
              size="sm"
              onClick={() => handleSearchModeChange('semantic')}
            >
              <Sparkles className="h-4 w-4 mr-2" />
              Semantic Search
            </Button>

            <div className="ml-auto flex gap-1">
              <Button
                variant={viewMode === 'individual' ? 'default' : 'outline'}
                size="sm"
                onClick={() => setViewMode('individual')}
                title="Individual images"
              >
                <LayoutGrid className="h-4 w-4" />
              </Button>
              <Button
                variant={viewMode === 'grouped' ? 'default' : 'outline'}
                size="sm"
                onClick={() => setViewMode('grouped')}
                title="Variant groups"
              >
                <Layers className="h-4 w-4" />
              </Button>
            </div>
          </div>

          {/* Search bar */}
          <div className="flex gap-2 mb-3">
            <form onSubmit={handleSemanticSearch} className="relative flex-1 flex gap-2">
              <div className="relative flex-1">
                {searchMode === 'text' ? (
                  <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                ) : (
                  <Sparkles className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                )}
                <Input
                  type="text"
                  placeholder={
                    searchMode === 'text'
                      ? 'Search by name, author, or tags...'
                      : 'Describe the scene you\'re looking for...'
                  }
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="pl-9"
                />
              </div>

              {/* Semantic search button */}
              {searchMode === 'semantic' && (
                <Button type="submit" disabled={isSearching || !searchQuery.trim()}>
                  {isSearching ? 'Searching...' : 'Search'}
                </Button>
              )}
            </form>

            {/* Import button */}
            <Button
              variant="outline"
              size="icon"
              onClick={() => setShowImport(true)}
              title={importActive ? 'Import in progress - click to view' : 'Import images'}
              className="relative"
            >
              <Upload className="h-4 w-4" />
              {importActive && (
                <span className="absolute -top-1 -right-1 h-3 w-3 rounded-full bg-primary animate-pulse" />
              )}
            </Button>

            {/* Filter panel button */}
            <Sheet open={showFilters} onOpenChange={setShowFilters}>
              <Button
                variant="outline"
                size="icon"
                className="relative"
                onClick={() => setShowFilters(true)}
              >
                <Filter className="h-4 w-4" />
                {(selectedAuthors.length > 0 || selectedTags.length > 0) && (
                  <span className="absolute -top-1 -right-1 h-4 w-4 rounded-full bg-primary text-[10px] font-bold text-primary-foreground flex items-center justify-center">
                    {selectedAuthors.length + selectedTags.length}
                  </span>
                )}
              </Button>

              <SheetContent className="w-full sm:max-w-md overflow-y-auto">
                <SheetHeader>
                  <SheetTitle>Filters</SheetTitle>
                  <SheetDescription>
                    Filter images by author and tags. Multiple selections within a category use OR logic, across categories use AND.
                  </SheetDescription>
                </SheetHeader>

                {/* Filter search */}
                <div className="mt-4 mb-4">
                  <div className="relative">
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                    <Input
                      type="text"
                      placeholder="Search filters..."
                      value={filterSearch}
                      onChange={(e) => setFilterSearch(e.target.value)}
                      className="pl-9"
                    />
                  </div>
                </div>

                {/* Authors section */}
                {filteredAuthors.length > 0 && (
                  <div className="mb-6">
                    <h3 className="font-semibold text-sm mb-3 flex items-center justify-between">
                      Authors
                      {selectedAuthors.length > 0 && (
                        <span className="text-xs font-normal text-muted-foreground">
                          {selectedAuthors.length} selected
                        </span>
                      )}
                    </h3>
                    <div className="space-y-2">
                      {filteredAuthors.map((author) => (
                        <div key={author} className="flex items-center space-x-2">
                          <Checkbox
                            id={`author-${author}`}
                            checked={selectedAuthors.includes(author)}
                            onCheckedChange={() => toggleAuthor(author)}
                          />
                          <label
                            htmlFor={`author-${author}`}
                            className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70 cursor-pointer"
                          >
                            {author}
                          </label>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Tag categories */}
                {Object.entries(filteredTagsByCategory).map(([category, values]) => {
                  const selectedCount = selectedTags.filter((t) => t.startsWith(`${category}:`)).length
                  return (
                    <div key={category} className="mb-6">
                      <h3 className="font-semibold text-sm mb-3 capitalize flex items-center justify-between">
                        {category}
                        {selectedCount > 0 && (
                          <span className="text-xs font-normal text-muted-foreground">
                            {selectedCount} selected
                          </span>
                        )}
                      </h3>
                      <div className="space-y-2">
                        {values.map((value) => {
                          const tagFilter = `${category}:${value}`
                          return (
                            <div key={tagFilter} className="flex items-center space-x-2">
                              <Checkbox
                                id={tagFilter}
                                checked={selectedTags.includes(tagFilter)}
                                onCheckedChange={() => toggleTag(category, value)}
                              />
                              <label
                                htmlFor={tagFilter}
                                className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70 cursor-pointer capitalize"
                              >
                                {value}
                              </label>
                            </div>
                          )
                        })}
                      </div>
                    </div>
                  )
                })}

                {/* No results */}
                {filteredAuthors.length === 0 && Object.keys(filteredTagsByCategory).length === 0 && (
                  <div className="text-center py-8 text-muted-foreground">
                    <p>No filters match "{filterSearch}"</p>
                  </div>
                )}

                {/* Clear all button */}
                {hasActiveFilters && (
                  <div className="mt-6 pt-6 border-t">
                    <Button variant="outline" onClick={clearFilters} className="w-full">
                      Clear all filters
                    </Button>
                  </div>
                )}
              </SheetContent>
            </Sheet>

            {hasActiveFilters && (
              <Button variant="ghost" size="icon" onClick={clearFilters} title="Clear all filters">
                <X className="h-4 w-4" />
              </Button>
            )}
          </div>

          {/* Active filters display */}
          {hasActiveFilters && (
            <div className="flex flex-wrap gap-2">
              {selectedAuthors.map((author) => (
                <Badge key={author} variant="secondary" className="gap-1">
                  Author: {author}
                  <X
                    className="h-3 w-3 cursor-pointer"
                    onClick={() => toggleAuthor(author)}
                  />
                </Badge>
              ))}
              {selectedTags.map((tag) => {
                const [category, value] = tag.split(':')
                return (
                  <Badge key={tag} variant="secondary" className="gap-1">
                    {category}: {value}
                    <X
                      className="h-3 w-3 cursor-pointer"
                      onClick={() => toggleTag(category, value)}
                    />
                  </Badge>
                )
              })}
            </div>
          )}
        </div>
      </header>

      {/* Main content */}
      <main className="flex-1 overflow-hidden">
        {isLoadingImages || isSearching ? (
          <div className="flex h-full items-center justify-center">
            <p className="text-muted-foreground">
              {isSearching ? 'Searching...' : 'Loading images...'}
            </p>
          </div>
        ) : filteredImages.length === 0 ? (
          <div className="flex h-full items-center justify-center">
            <div className="text-center max-w-md">
              <p className="text-muted-foreground mb-2">
                {hasActiveFilters ? 'No images found matching your filters' : 'No images available'}
              </p>
              {searchMode === 'semantic' && searchQuery && (
                <p className="text-sm text-muted-foreground">
                  Try: "abandoned mine with crystals" or "winter forest temple"
                </p>
              )}
              {hasActiveFilters && (
                <Button variant="outline" size="sm" onClick={clearFilters} className="mt-4">
                  Clear all filters
                </Button>
              )}
            </div>
          </div>
        ) : viewMode === 'individual' ? (
          <ImageGrid
            images={filteredImages}
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
          onNext={selectedImage.index < filteredImages.length - 1 ? handleNext : undefined}
          onPrevious={selectedImage.index > 0 ? handlePrevious : undefined}
          onImageChange={(newImage) => {
            setSelectedImage((prev) => prev ? { ...prev, image: newImage } : null)
          }}
        />
      )}

      {/* Import dialog */}
      <ImportDialog open={showImport} onOpenChange={setShowImport} onActiveChange={setImportActive} />
    </div>
  )
}
