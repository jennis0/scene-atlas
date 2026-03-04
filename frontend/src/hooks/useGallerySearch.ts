import { useState, useMemo, useRef, useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { searchApi } from '@/lib/api'
import { QUERY_KEYS } from '@/lib/queryKeys'
import { useImageGrouping } from '@/hooks/useImageGrouping'
import type { Image, ImageGroup, SearchParams, SortBy, SortDir, ViewMode, FacetData } from '@/types'
import type { ActiveFilter, ImageTypeFilter } from '@/components/import/fileFilter'

// ---------------------------------------------------------------------------
// Sort options
// ---------------------------------------------------------------------------

export const SORT_OPTIONS: { value: SortBy; dir: SortDir; label: string; queryOnly?: boolean }[] = [
  { value: 'created_at', dir: 'desc', label: 'Newest first' },
  { value: 'created_at', dir: 'asc', label: 'Oldest first' },
  { value: 'name', dir: 'asc', label: 'Name A\u2013Z' },
  { value: 'name', dir: 'desc', label: 'Name Z\u2013A' },
  { value: 'relevance', dir: 'desc', label: 'Relevance', queryOnly: true },
]

const DEFAULT_SORT_KEY = 'created_at:desc'

export function parseSortKey(key: string): [SortBy, SortDir] {
  const [s, d] = key.split(':') as [SortBy, SortDir]
  return [s, d]
}

export function loadSortKey(): string {
  const stored = localStorage.getItem('gallery-sort')
  if (stored && SORT_OPTIONS.some((o) => `${o.value}:${o.dir}` === stored)) return stored
  return DEFAULT_SORT_KEY
}

// ---------------------------------------------------------------------------
// URL <-> filter serialisation helpers
// ---------------------------------------------------------------------------

export function parseFiltersFromUrl(params: URLSearchParams): ActiveFilter[] {
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

export function buildUrlParams(
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
// Return type
// ---------------------------------------------------------------------------

export interface UseGallerySearchReturn {
  // State
  searchInput: string
  setSearchInput: (value: string) => void
  submittedQuery: string
  filters: ActiveFilter[]
  imageType: ImageTypeFilter
  sortKey: string
  minScore: number
  setMinScore: (value: number) => void
  viewMode: ViewMode
  setViewMode: (mode: ViewMode) => void

  // Derived values
  isSemantic: boolean
  isTextOnly: boolean
  hasActiveSearch: boolean
  searchModeSuffix: string
  showRelevanceSlider: boolean
  totalBeforeFilter: number
  filteredCount: number
  sortBy: SortBy
  sortDir: SortDir

  // Data
  facets: FacetData | undefined
  searchParams: SearchParams
  displayImages: Image[]
  imageGroups: ImageGroup[]
  isSearching: boolean

  // Handlers
  handleSubmit: (e: React.FormEvent) => void
  handleSortChange: (newKey: string) => void
  handleFiltersChange: (newFilters: ActiveFilter[]) => void
  handleImageTypeChange: (type: ImageTypeFilter) => void
  clearSearch: () => void
  clearAll: () => void
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useGallerySearch(): UseGallerySearchReturn {
  const [urlParams, setUrlParams] = useSearchParams()

  // Search state -- initialised from URL so searches are bookmarkable
  const [searchInput, setSearchInput] = useState(() => urlParams.get('q') ?? '')
  const [submittedQuery, setSubmittedQuery] = useState(() => urlParams.get('q') ?? '')
  const [filters, setFilters] = useState<ActiveFilter[]>(() => parseFiltersFromUrl(urlParams))
  const [imageType, setImageType] = useState<ImageTypeFilter>(
    () => (urlParams.get('image_type') as ImageTypeFilter) || 'all',
  )

  // Sort preference -- persisted in localStorage
  const [sortKey, setSortKey] = useState(loadSortKey)
  const [sortBy, sortDir] = parseSortKey(sortKey)

  // Relevance threshold -- slider value, applied client-side against returned scores
  const [minScore, setMinScoreState] = useState(() => {
    const stored = localStorage.getItem('gallery-relevance')
    return stored ? parseFloat(stored) : 0.2
  })
  const relevanceSaveRef = useRef<ReturnType<typeof setTimeout>>()
  const setMinScore = useCallback((value: number) => {
    setMinScoreState(value)
    clearTimeout(relevanceSaveRef.current)
    relevanceSaveRef.current = setTimeout(() => {
      localStorage.setItem('gallery-relevance', String(value))
    }, 300)
  }, [])

  // View mode -- persisted in localStorage
  const [viewMode, setViewModeState] = useState<ViewMode>(
    () => (localStorage.getItem('gallery-view-mode') as ViewMode) || 'individual',
  )
  const setViewMode = useCallback((mode: ViewMode) => {
    setViewModeState(mode)
    localStorage.setItem('gallery-view-mode', mode)
  }, [])

  // Facets -- lightweight cached fetch
  const { data: facets } = useQuery({
    queryKey: QUERY_KEYS.searchFacets,
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

  // Search query -- always enabled, returns full library when no params
  const { data: searchResults, isLoading: isSearching } = useQuery({
    queryKey: [...QUERY_KEYS.search, searchParams],
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

  const handleSubmit = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault()
      setSubmittedQuery(searchInput)
      // Auto-switch to relevance sort when entering a search query
      if (searchInput.trim()) {
        setSortKey('relevance:desc')
      } else {
        // Clearing query via submit -- revert to saved sort preference
        setSortKey(loadSortKey())
      }
      setUrlParams(buildUrlParams(searchInput, filters, imageType))
    },
    [searchInput, filters, imageType, setUrlParams],
  )

  const handleSortChange = useCallback((newKey: string) => {
    setSortKey(newKey)
    // Persist non-relevance sorts as the user's preference
    if (newKey !== 'relevance:desc') {
      localStorage.setItem('gallery-sort', newKey)
    }
  }, [])

  const handleFiltersChange = useCallback(
    (newFilters: ActiveFilter[]) => {
      setFilters(newFilters)
      setUrlParams(buildUrlParams(submittedQuery, newFilters, imageType))
    },
    [submittedQuery, imageType, setUrlParams],
  )

  const handleImageTypeChange = useCallback(
    (type: ImageTypeFilter) => {
      setImageType(type)
      setUrlParams(buildUrlParams(submittedQuery, filters, type))
    },
    [submittedQuery, filters, setUrlParams],
  )

  const clearSearch = useCallback(() => {
    setSearchInput('')
    setSubmittedQuery('')
    setSortKey(loadSortKey())
    setUrlParams(buildUrlParams('', filters, imageType))
  }, [filters, imageType, setUrlParams])

  const clearAll = useCallback(() => {
    setSearchInput('')
    setSubmittedQuery('')
    setFilters([])
    setImageType('all')
    setSortKey(loadSortKey())
    setUrlParams(new URLSearchParams())
  }, [setUrlParams])

  // Result count label suffix
  const searchModeSuffix = isSemantic ? ' \u00b7 visual' : isTextOnly ? ' \u00b7 keyword' : ''

  return {
    // State
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

    // Derived values
    isSemantic,
    isTextOnly,
    hasActiveSearch,
    searchModeSuffix,
    showRelevanceSlider,
    totalBeforeFilter,
    filteredCount,
    sortBy,
    sortDir,

    // Data
    facets,
    searchParams,
    displayImages,
    imageGroups,
    isSearching,

    // Handlers
    handleSubmit,
    handleSortChange,
    handleFiltersChange,
    handleImageTypeChange,
    clearSearch,
    clearAll,
  }
}
