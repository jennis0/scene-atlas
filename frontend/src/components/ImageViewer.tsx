import { useMemo, useState, useEffect, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { ChevronLeft, ChevronRight, X, Search, Pencil, Edit, SlidersHorizontal } from 'lucide-react'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { imageApi, tagApi, searchApi, getImageUrl, getThumbnailUrl } from '@/lib/api'
import { useGetTagColor } from '@/contexts/TagColorContext'
import { TagPicker } from '@/components/import/TagPicker'
import { GridToggle } from '@/components/import/GridToggle'
import { FilterMenuContent, FilterChipList, type FilterOptionGroup } from '@/components/FilterMenuContent'
import type { ActiveFilter } from '@/components/import/fileFilter'
import type { Image, TagData } from '@/types'
import { parseTagVocabulary, type ParsedTagVocab } from '@/components/import/types'

interface ImageViewerProps {
  image: Image
  onClose: () => void
  onNext?: () => void
  onPrevious?: () => void
  onImageChange?: (image: Image) => void
  onEditGroup?: (groupId: number) => void
}

// Dot-grid canvas background — gives the image a defined "stage"
const CANVAS_STYLE: React.CSSProperties = {
  background: 'hsl(222 22% 6%)',
  backgroundImage: 'radial-gradient(circle, rgba(255,255,255,0.045) 1px, transparent 1px)',
  backgroundSize: '24px 24px',
}

export function ImageViewer({ image, onClose, onNext, onPrevious, onImageChange, onEditGroup }: ImageViewerProps) {
  const getTagColor = useGetTagColor()
  const queryClient = useQueryClient()

  // Fresh data for the displayed image; initialData avoids flash on navigation
  const { data: displayImage } = useQuery({
    queryKey: ['image', image.id],
    queryFn: () => imageApi.get(image.id),
    initialData: image,
  })

  const { data: variants } = useQuery({
    queryKey: ['variants', image.id],
    queryFn: () => imageApi.getVariants(image.id),
  })

  const { data: facets } = useQuery({
    queryKey: ['searchFacets'],
    queryFn: () => searchApi.facets(),
    staleTime: 60_000,
  })

  const { data: tagCategories } = useQuery({
    queryKey: ['tagCategories'],
    queryFn: () => tagApi.getCategories(),
    staleTime: 5 * 60_000,
  })

  // ── Refs ──────────────────────────────────────────────────────────────────
  const scrollContainerRef = useRef<HTMLDivElement>(null)
  // Set to the target image ID before a within-group variant click so the reset effect skips.
  const preserveStateRef = useRef(false)
  // Tracks the image.id we last processed in the reset effect.
  // Prevents React Strict Mode's double-invocation from running the reset twice.
  const lastProcessedIdRef = useRef<number | null>(null)

  // ── Local UI state ────────────────────────────────────────────────────────
  const [variantSearch, setVariantSearch] = useState('')
  const [variantFilters, setVariantFilters] = useState<ActiveFilter[]>([])
  const [filterPopoverOpen, setFilterPopoverOpen] = useState(false)
  const [editingName, setEditingName] = useState(false)
  const [nameDraft, setNameDraft] = useState(image.name)
  const [editingSV, setEditingSV] = useState(false)
  const [subVariantDraft, setSubVariantDraft] = useState(image.sub_variant ?? '')
  const [gridWidthDraft, setGridWidthDraft] = useState<string>(image.grid_width?.toString() ?? '')
  const [gridHeightDraft, setGridHeightDraft] = useState<string>(image.grid_height?.toString() ?? '')

  // Reset UI state on image navigation (not on within-group variant click).
  // lastProcessedIdRef guards against React Strict Mode running this effect twice
  // for the same image.id — without it the second run would clear preserveStateRef
  // and reset scroll even on variant clicks.
  useEffect(() => {
    if (lastProcessedIdRef.current === image.id) return
    lastProcessedIdRef.current = image.id

    if (preserveStateRef.current) {
      preserveStateRef.current = false
      return
    }
    const src = displayImage ?? image
    setNameDraft(src.name)
    setEditingName(false)
    setSubVariantDraft(src.sub_variant ?? '')
    setEditingSV(false)
    setVariantSearch('')
    setVariantFilters([])
    setGridWidthDraft(src.grid_width?.toString() ?? '')
    setGridHeightDraft(src.grid_height?.toString() ?? '')
    if (scrollContainerRef.current) scrollContainerRef.current.scrollTop = 0
  }, [image.id])

  // Sync drafts when fresh image data arrives (e.g. after a patch succeeds)
  useEffect(() => {
    if (!editingName) setNameDraft(displayImage?.name ?? '')
    if (!editingSV) setSubVariantDraft(displayImage?.sub_variant ?? '')
    setGridWidthDraft(displayImage?.grid_width?.toString() ?? '')
    setGridHeightDraft(displayImage?.grid_height?.toString() ?? '')
  }, [displayImage?.name, displayImage?.sub_variant, displayImage?.grid_width, displayImage?.grid_height])

  // Keyboard shortcuts — skip when any input/select/textarea is focused
  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if (editingName || editingSV) return
      const target = e.target as HTMLElement
      if (target.tagName === 'INPUT' || target.tagName === 'SELECT' || target.tagName === 'TEXTAREA') return
      if (e.key === 'Escape') onClose()
      if (e.key === 'ArrowRight') onNext?.()
      if (e.key === 'ArrowLeft') onPrevious?.()
    }
    window.addEventListener('keydown', handleKey)
    return () => window.removeEventListener('keydown', handleKey)
  }, [onClose, onNext, onPrevious, editingName, editingSV])

  // ── Mutations ─────────────────────────────────────────────────────────────
  const invalidateImage = () => {
    queryClient.invalidateQueries({ queryKey: ['image', image.id] })
    queryClient.invalidateQueries({ queryKey: ['variants', image.id] })
  }

  const renameMutation = useMutation({
    mutationFn: (name: string) => imageApi.patch(image.id, { name }),
    onSuccess: (updated) => {
      queryClient.setQueryData(['image', image.id], updated)
      onImageChange?.(updated)
      setEditingName(false)
    },
  })

  const patchMutation = useMutation({
    mutationFn: (payload: Parameters<typeof imageApi.patch>[1]) => imageApi.patch(image.id, payload),
    onSuccess: (updated) => {
      queryClient.setQueryData(['image', image.id], updated)
      onImageChange?.(updated)
    },
  })

  const addTagMutation = useMutation({
    mutationFn: ({ category, value }: { category: string; value: string }) =>
      tagApi.addToImage(image.id, { category, value }),
    onSuccess: invalidateImage,
  })

  const removeTagMutation = useMutation({
    mutationFn: (tagId: number) => tagApi.removeTag(tagId),
    onSuccess: invalidateImage,
  })

  // ── Derived data ──────────────────────────────────────────────────────────
  const img = displayImage ?? image

  // Build tag vocabulary from full category list (not facets) so new vocabulary
  // values with zero images are still selectable in the tag picker.
  const tagVocab = useMemo((): ParsedTagVocab[] =>
    tagCategories ? parseTagVocabulary(tagCategories) : [],
    [tagCategories]
  )

  // Convert Image tags → TagData for TagPicker deduplication
  const existingTagData = useMemo((): TagData[] =>
    (img.tags ?? []).map((t) => ({
      category: t.category,
      value: t.value,
      confidence: t.confidence,
      source: t.source,
    })),
    [img.tags]
  )

  // Unique sub_variants across the loaded variant group (datalist suggestions)
  const existingSubVariants = useMemo(() =>
    [...new Set((variants ?? []).map((v) => v.sub_variant).filter((sv): sv is string => sv != null))].sort(),
    [variants]
  )

  // Filter options derived from the loaded variant list
  const variantFilterGroups = useMemo((): FilterOptionGroup[] => {
    if (!variants || variants.length <= 1) return []
    const groups: FilterOptionGroup[] = []

    // Sub-variants
    const subVariants = [
      ...new Set(variants.map((v) => v.sub_variant).filter((sv): sv is string => sv != null)),
    ].sort()
    if (subVariants.length > 0) {
      groups.push({
        id: 'subVariant',
        label: 'Variant',
        type: 'subVariant',
        options: subVariants.map((sv) => ({
          filterValue: sv,
          label: sv,
          filterLabel: sv,
          count: variants.filter((v) => v.sub_variant === sv).length,
        })),
      })
    }

    // Tag categories present across variants
    const tagMap = new Map<string, Map<string, number>>()
    for (const v of variants) {
      for (const tag of v.tags ?? []) {
        if (!tagMap.has(tag.category)) tagMap.set(tag.category, new Map())
        const cm = tagMap.get(tag.category)!
        cm.set(tag.value, (cm.get(tag.value) ?? 0) + 1)
      }
    }
    for (const [cat, valMap] of tagMap) {
      groups.push({
        id: cat,
        label: cat,
        type: 'tag',
        options: [...valMap.entries()].map(([val, count]) => ({
          filterValue: `${cat}:${val}`,
          label: val,
          filterLabel: `${cat}: ${val}`,
          count,
        })),
      })
    }

    return groups
  }, [variants])

  const filteredVariants = useMemo(() => {
    let result = variants ?? []

    if (variantSearch.trim()) {
      const q = variantSearch.toLowerCase()
      result = result.filter(
        (v) =>
          v.name.toLowerCase().includes(q) ||
          v.sub_variant?.toLowerCase().includes(q) ||
          filenameStem(v.filename).toLowerCase().includes(q),
      )
    }

    const includes = variantFilters.filter((f) => !f.exclude)
    const excludes = variantFilters.filter((f) => f.exclude)
    if (includes.length) result = result.filter((v) => includes.every((f) => matchesFilter(v, f)))
    if (excludes.length) result = result.filter((v) => !excludes.some((f) => matchesFilter(v, f)))

    return result
  }, [variants, variantSearch, variantFilters])

  const variantSections = useMemo(
    () => (filteredVariants.length > 1 ? partitionBySubVariant(filteredVariants) : []),
    [filteredVariants],
  )

  const hasVariants = variants && variants.length > 1
  // True when there are dimensions to filter on (not just whether filters are active)
  const hasFilterableData = variantFilterGroups.length > 0
  const hasActiveFilters = variantFilters.length > 0

  // ── Handlers ─────────────────────────────────────────────────────────────
  const handleVariantClick = (variant: Image) => {
    preserveStateRef.current = true
    onImageChange?.(variant)
  }

  const saveName = () => {
    const trimmed = nameDraft.trim()
    if (trimmed && trimmed !== img.name) renameMutation.mutate(trimmed)
    else setEditingName(false)
  }

  const handleNameKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') saveName()
    if (e.key === 'Escape') { setNameDraft(img.name); setEditingName(false) }
  }

  const saveSubVariant = () => {
    const trimmed = subVariantDraft.trim() || null
    if (trimmed !== img.sub_variant) patchMutation.mutate({ sub_variant: trimmed })
    setEditingSV(false)
  }

  const handleSVKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') saveSubVariant()
    if (e.key === 'Escape') { setSubVariantDraft(img.sub_variant ?? ''); setEditingSV(false) }
  }

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-8"
      style={{ background: 'rgba(0,0,0,0.88)' }}
      onClick={onClose}
    >
      <div
        className="relative flex w-full rounded-xl overflow-hidden border border-border/20 shadow-2xl shadow-black/70"
        style={{ maxWidth: '1600px', height: '88vh' }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* ── Image canvas ── */}
        <div
          className="flex-1 relative flex items-center justify-center min-w-0"
          style={CANVAS_STYLE}
        >
          {/* Amber stripe — canvas half: transparent at left edge, full at join */}
          <div className="absolute top-0 inset-x-0 h-0.5 bg-gradient-to-r from-transparent to-primary/80 pointer-events-none z-10" />

          <img
            src={getImageUrl(img)}
            alt={img.name}
            className="max-h-full max-w-full object-contain shadow-2xl shadow-black/60"
          />
          {onPrevious && (
            <button
              onClick={(e) => { e.stopPropagation(); onPrevious() }}
              className="absolute left-3 top-1/2 -translate-y-1/2 h-10 w-10 rounded-full bg-black/50 hover:bg-black/75 text-white/80 hover:text-white flex items-center justify-center transition-all"
            >
              <ChevronLeft className="h-5 w-5" />
            </button>
          )}
          {onNext && (
            <button
              onClick={(e) => { e.stopPropagation(); onNext() }}
              className="absolute right-3 top-1/2 -translate-y-1/2 h-10 w-10 rounded-full bg-black/50 hover:bg-black/75 text-white/80 hover:text-white flex items-center justify-center transition-all"
            >
              <ChevronRight className="h-5 w-5" />
            </button>
          )}
        </div>

        {/* ── Sidebar ── */}
        <div className="w-[440px] shrink-0 flex flex-col border-l border-border/20 bg-card overflow-hidden">
          {/* Amber stripe — sidebar half: full at join, transparent at right edge */}
          <div className="h-0.5 shrink-0 bg-gradient-to-l from-transparent to-primary/80" />

          {/* Controls row */}
          <div className="flex items-center justify-between px-4 pt-3 pb-1.5 shrink-0">
            {img.variant_group_id !== null && onEditGroup ? (
              <button
                onClick={() => onEditGroup(img.variant_group_id!)}
                className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
              >
                <Edit className="h-3.5 w-3.5" />
                Edit group
              </button>
            ) : (
              <div />
            )}
            <button
              onClick={onClose}
              className="h-7 w-7 rounded flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors"
            >
              <X className="h-4 w-4" />
            </button>
          </div>

          {/* ── Image info (fixed — stays visible while variants scroll) ── */}
          <div className="px-4 pb-4 shrink-0 border-b border-border/30">

              {/* Name (inline-editable) */}
              <div className="group/name flex items-start gap-2 mb-0.5">
                {editingName ? (
                  <input
                    autoFocus
                    value={nameDraft}
                    onChange={(e) => setNameDraft(e.target.value)}
                    onBlur={saveName}
                    onKeyDown={handleNameKeyDown}
                    className="font-display text-xl font-semibold bg-transparent border-b border-primary/70 focus:outline-none text-foreground flex-1 min-w-0 pb-px"
                  />
                ) : (
                  <h2
                    className="font-display text-xl font-semibold text-foreground cursor-text flex-1 min-w-0 leading-tight"
                    onClick={() => { setNameDraft(img.name); setEditingName(true) }}
                    title="Click to rename"
                  >
                    {img.name}
                  </h2>
                )}
                {!editingName && (
                  <button
                    onClick={() => { setNameDraft(img.name); setEditingName(true) }}
                    className="opacity-0 group-hover/name:opacity-60 hover:!opacity-100 transition-opacity mt-1 text-muted-foreground shrink-0"
                    title="Rename"
                  >
                    <Pencil className="h-3.5 w-3.5" />
                  </button>
                )}
              </div>

              {/* Author */}
              <p className="text-sm text-muted-foreground mb-3">by {img.author}</p>

              {/* Sub-variant — inline editable property row */}
              <div className="group/sv flex items-center gap-2 mb-2 min-w-0">
                <span className="text-[10px] uppercase tracking-wider text-muted-foreground/60 w-[72px] shrink-0">
                  Subgroup
                </span>
                {editingSV ? (
                  <>
                    <input
                      autoFocus
                      value={subVariantDraft}
                      onChange={(e) => setSubVariantDraft(e.target.value)}
                      onBlur={saveSubVariant}
                      onKeyDown={handleSVKeyDown}
                      list="sv-suggestions"
                      placeholder="e.g. MA / No Grid"
                      className="flex-1 min-w-0 text-xs bg-transparent border-b border-primary/70 focus:outline-none text-foreground pb-px"
                    />
                    <datalist id="sv-suggestions">
                      {existingSubVariants.map((sv) => <option key={sv} value={sv} />)}
                    </datalist>
                  </>
                ) : (
                  <>
                    <span
                      onClick={() => { setSubVariantDraft(img.sub_variant ?? ''); setEditingSV(true) }}
                      className="flex-1 min-w-0 text-xs cursor-text truncate"
                      title={img.sub_variant ?? undefined}
                    >
                      {img.sub_variant
                        ? <span className="text-foreground/80">{img.sub_variant}</span>
                        : <span className="text-muted-foreground/30 italic">none</span>
                      }
                    </span>
                    <button
                      onClick={() => { setSubVariantDraft(img.sub_variant ?? ''); setEditingSV(true) }}
                      className="opacity-0 group-hover/sv:opacity-40 hover:!opacity-100 transition-opacity text-muted-foreground shrink-0"
                      title="Edit sub-variant"
                    >
                      <Pencil className="h-3 w-3" />
                    </button>
                    {img.sub_variant && (
                      <button
                        onClick={() => patchMutation.mutate({ sub_variant: null })}
                        className="opacity-0 group-hover/sv:opacity-40 hover:!opacity-100 transition-opacity text-muted-foreground shrink-0"
                        title="Clear sub-variant"
                      >
                        <X className="h-3 w-3" />
                      </button>
                    )}
                  </>
                )}
              </div>

              {/* Gridded toggle + optional grid size inputs */}
              <div className="flex items-center gap-3 flex-wrap mb-4">
                <GridToggle
                  value={img.gridded ?? null}
                  onChange={(v) => patchMutation.mutate({ gridded: v })}
                  disabled={patchMutation.isPending}
                />
                {img.gridded === true && (
                  <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                    <input
                      type="number"
                      value={gridWidthDraft}
                      onChange={(e) => setGridWidthDraft(e.target.value)}
                      onBlur={() => {
                        const w = parseInt(gridWidthDraft) || null
                        if (w !== img.grid_width) patchMutation.mutate({ grid_width: w })
                      }}
                      onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }}
                      placeholder="W"
                      min={1}
                      className="w-14 bg-secondary border border-border rounded px-2 py-1 text-foreground text-center placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary/40 text-xs [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none"
                    />
                    <span>×</span>
                    <input
                      type="number"
                      value={gridHeightDraft}
                      onChange={(e) => setGridHeightDraft(e.target.value)}
                      onBlur={() => {
                        const h = parseInt(gridHeightDraft) || null
                        if (h !== img.grid_height) patchMutation.mutate({ grid_height: h })
                      }}
                      onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }}
                      placeholder="H"
                      min={1}
                      className="w-14 bg-secondary border border-border rounded px-2 py-1 text-foreground text-center placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary/40 text-xs [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none"
                    />
                  </div>
                )}
              </div>

              {/* Color swatches + dimensions */}
              <div className="flex items-center gap-3 mb-4">
                {img.colors && img.colors.length > 0 && (
                  <div className="flex gap-1">
                    {img.colors
                      .sort((a, b) => a.color_order - b.color_order)
                      .map((color) => (
                        <div
                          key={color.id}
                          className="h-5 w-5 rounded-full border border-black/25 shadow-sm"
                          style={{ backgroundColor: color.color_hex }}
                          title={`${color.color_hex} (${(color.percentage * 100).toFixed(1)}%)`}
                        />
                      ))}
                  </div>
                )}
                <p className="text-[11px] text-muted-foreground">
                  {img.width}×{img.height} · {(img.file_size / 1024 / 1024).toFixed(1)} MB
                  <span className="ml-1 opacity-40 font-mono text-[10px]">{filenameStem(img.filename)}</span>
                </p>
              </div>

              {/* Tags — colour indicates category, so show capitalised value only */}
              <div className="flex flex-wrap gap-1.5">
                {img.tags?.map((tag) => {
                  const colors = getTagColor(tag.category)
                  return (
                    <span
                      key={tag.id}
                      title={tag.category}
                      className={`inline-flex items-center gap-1 text-[11px] rounded-full border px-2 py-px ${colors.bg} ${colors.text} ${colors.border}`}
                    >
                      <span className="capitalize">{tag.value}</span>
                      <button
                        onClick={() => removeTagMutation.mutate(tag.id)}
                        disabled={removeTagMutation.isPending}
                        className="opacity-40 hover:opacity-100 transition-opacity ml-0.5 disabled:cursor-not-allowed"
                        title={`Remove ${tag.category}: ${tag.value}`}
                      >
                        <X className="h-2.5 w-2.5" />
                      </button>
                    </span>
                  )
                })}

                <TagPicker
                  vocab={tagVocab}
                  existingTags={existingTagData}
                  onAdd={(tag) => addTagMutation.mutate({ category: tag.category, value: tag.value })}
                />
              </div>
          </div>

          {/* ── Variants section (only this scrolls) ── */}
          {hasVariants && (
            <div ref={scrollContainerRef} className="flex-1 min-h-0 overflow-y-auto">
              {/* Sticky header: label + search + filter button */}
              <div className="sticky top-0 z-10 bg-card border-b border-border/30">
                  <div className="px-4 py-2 flex items-center gap-2">
                    <span className="text-sm font-semibold shrink-0">
                      Variants
                      <span className="ml-1.5 text-xs font-normal text-muted-foreground">
                        ({filteredVariants.length}
                        {(variantSearch || hasActiveFilters) && variants
                          ? `/${variants.length}`
                          : ''})
                      </span>
                    </span>

                    {/* Search */}
                    <div className="relative flex-1">
                      <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3 w-3 text-muted-foreground pointer-events-none" />
                      <input
                        value={variantSearch}
                        onChange={(e) => setVariantSearch(e.target.value)}
                        placeholder="Filter…"
                        className="w-full h-6 pl-6 pr-2 text-xs bg-secondary border border-border rounded focus:outline-none focus:ring-1 focus:ring-primary/40 text-foreground placeholder:text-muted-foreground"
                      />
                    </div>

                    {/* Filter button — always present, greyed when nothing to filter on */}
                    <Popover
                      open={hasFilterableData ? filterPopoverOpen : false}
                      onOpenChange={hasFilterableData ? setFilterPopoverOpen : undefined}
                    >
                      <PopoverTrigger asChild>
                        <button
                          disabled={!hasFilterableData}
                          className={`relative h-6 w-6 rounded flex items-center justify-center shrink-0 transition-colors ${
                            hasActiveFilters
                              ? 'bg-primary/20 text-primary border border-primary/40'
                              : hasFilterableData
                                ? 'text-muted-foreground hover:text-foreground hover:bg-secondary border border-transparent'
                                : 'text-muted-foreground/25 border border-transparent cursor-not-allowed'
                          }`}
                          title={hasFilterableData ? 'Filter variants' : 'No filterable dimensions'}
                        >
                          <SlidersHorizontal className="h-3 w-3" />
                          {hasActiveFilters && (
                            <span className="absolute -top-1 -right-1 h-3.5 w-3.5 rounded-full bg-primary text-[9px] font-bold text-primary-foreground flex items-center justify-center">
                              {variantFilters.length}
                            </span>
                          )}
                        </button>
                      </PopoverTrigger>
                      {hasFilterableData && (
                        <PopoverContent
                          align="end"
                          side="left"
                          className="w-[320px] p-0 h-[360px] flex flex-col"
                        >
                          <FilterMenuContent
                            groups={variantFilterGroups}
                            activeFilters={variantFilters}
                            onFiltersChange={setVariantFilters}
                          />
                        </PopoverContent>
                      )}
                    </Popover>
                  </div>

                  {/* Active filter chips */}
                  {hasActiveFilters && (
                    <div className="px-4 pb-2">
                      <FilterChipList
                        filters={variantFilters}
                        onFiltersChange={setVariantFilters}
                      />
                    </div>
                  )}
                </div>

                {/* Variant grid */}
                <div className="px-4 pt-3 pb-4">
                  {filteredVariants.length === 0 ? (
                    <p className="text-xs text-muted-foreground text-center py-6">No variants match</p>
                  ) : (
                    variantSections.map((section) => (
                      <div key={section.label} className="mb-3 last:mb-0">
                        {variantSections.length > 1 && (
                          <p className="text-[11px] font-medium text-muted-foreground mb-2 uppercase tracking-wider">
                            {section.label}
                          </p>
                        )}
                        <div className="grid grid-cols-2 gap-2">
                          {section.images.map((variant) => (
                            <VariantTile
                              key={variant.id}
                              variant={variant}
                              isActive={variant.id === img.id}
                              onClick={() => handleVariantClick(variant)}
                            />
                          ))}
                        </div>
                      </div>
                    ))
                  )}
                </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// ── Sub-components ────────────────────────────────────────────────────────────

function VariantTile({
  variant,
  isActive,
  onClick,
}: {
  variant: Image
  isActive: boolean
  onClick: () => void
}) {
  const label = filenameStem(variant.filename)

  return (
    <div
      className={`relative cursor-pointer overflow-hidden rounded-md transition-all duration-200 hover:scale-[1.03] ${
        isActive
          ? 'ring-2 ring-primary/70 shadow-lg shadow-primary/15'
          : 'ring-1 ring-border/40 hover:ring-primary/40'
      }`}
      onClick={onClick}
    >
      <div className="aspect-[4/3]">
        <img
          src={getThumbnailUrl(variant)}
          alt={label}
          className="h-full w-full object-cover"
          loading="lazy"
        />
      </div>
      <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/80 via-black/40 to-transparent pt-8 pb-1.5 px-1.5 pointer-events-none">
        <p className="text-[10px] text-white/90 truncate leading-tight">{label}</p>
        {variant.gridded && (
          <p className="text-[9px] text-white/50 leading-tight">
            {variant.grid_width && variant.grid_height
              ? `${variant.grid_width}×${variant.grid_height}`
              : 'Grid'}
          </p>
        )}
      </div>
      {isActive && (
        <div className="absolute inset-0 ring-2 ring-inset ring-primary/40 rounded-md pointer-events-none" />
      )}
    </div>
  )
}

// ── Helpers ───────────────────────────────────────────────────────────────────

interface VariantSection {
  label: string
  images: Image[]
}

function matchesFilter(v: Image, f: ActiveFilter): boolean {
  if (f.type === 'subVariant') return v.sub_variant === f.value
  if (f.type === 'tag') {
    const idx = f.value.indexOf(':')
    const cat = f.value.slice(0, idx)
    const val = f.value.slice(idx + 1)
    return v.tags?.some((t) => t.category === cat && t.value === val) ?? false
  }
  return true
}

function partitionBySubVariant(variants: Image[]): VariantSection[] {
  const groups = new Map<string, Image[]>()
  const order: string[] = []

  for (const v of variants) {
    const key = v.sub_variant || 'Other'
    if (!groups.has(key)) { groups.set(key, []); order.push(key) }
    groups.get(key)!.push(v)
  }

  if (order.length <= 1) return [{ label: order[0] ?? 'All variants', images: variants }]
  return order.map((label) => ({ label, images: groups.get(label)! }))
}

function filenameStem(filename: string): string {
  return filename.replace(/\.[^.]+$/, '')
}
