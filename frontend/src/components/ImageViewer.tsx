import { useMemo, useState, useEffect, useRef } from 'react'
import { useQuery, useMutation, useQueryClient, keepPreviousData } from '@tanstack/react-query'
import {
  ChevronLeft,
  ChevronRight,
  X,
  Search,
  Pencil,
  Edit,
  SlidersHorizontal,
  Download,
  FolderDown,
  Trash2,
} from 'lucide-react'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { SceneTile } from '@/components/SceneTile'
import { SubgroupDropdown } from '@/components/SubgroupDropdown'
import { imageApi, tagApi, getImageUrl, getGroupDownloadUrl } from '@/lib/api'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { useGetTagColor } from '@/contexts/TagColorContext'
import { TagPicker } from '@/components/import/TagPicker'
import { GridToggle } from '@/components/import/GridToggle'
import {
  FilterMenuContent,
  FilterChipList,
  type FilterOptionGroup,
} from '@/components/FilterMenuContent'
import type { ActiveFilter, ImageTypeFilter } from '@/components/import/fileFilter'
import type { Image, TagData } from '@/types'
import { parseTagVocabulary, type ParsedTagVocab } from '@/components/import/types'

interface ImageViewerProps {
  image: Image
  onClose: () => void
  onNext?: () => void
  onPrevious?: () => void
  onImageChange?: (image: Image) => void
  onEditGroup?: (groupId: number) => void
  onDelete?: (imageId: number) => void
}

// Dot-grid canvas background — gives the image a defined "stage"
const CANVAS_STYLE: React.CSSProperties = {
  background: 'hsl(222 22% 6%)',
  backgroundImage: 'radial-gradient(circle, rgba(255,255,255,0.045) 1px, transparent 1px)',
  backgroundSize: '24px 24px',
}

export function ImageViewer({
  image,
  onClose,
  onNext,
  onPrevious,
  onImageChange,
  onEditGroup,
  onDelete,
}: ImageViewerProps) {
  const getTagColor = useGetTagColor()
  const queryClient = useQueryClient()

  // Fresh data for the displayed image; initialData avoids flash on navigation
  const { data: displayImage } = useQuery({
    queryKey: ['image', image.id],
    queryFn: () => imageApi.get(image.id),
    initialData: image,
  })

  const { data: scenes } = useQuery({
    queryKey: ['scenes', image.id],
    queryFn: () => imageApi.getScenes(image.id),
    placeholderData: keepPreviousData,
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
  const [sceneSearch, setVariantSearch] = useState('')
  const [sceneTypeFilter, setSceneTypeFilter] = useState<ImageTypeFilter>('all')
  const [sceneFilters, setVariantFilters] = useState<ActiveFilter[]>([])
  const [filterPopoverOpen, setFilterPopoverOpen] = useState(false)
  const [editingName, setEditingName] = useState(false)
  const [nameDraft, setNameDraft] = useState(image.name)
  const [editingSV, setEditingSV] = useState(false)
  const [downloading, setDownloading] = useState(false)
  const [downloadingGroup, setDownloadingGroup] = useState(false)
  const [confirmingDelete, setConfirmingDelete] = useState(false)
  const [gridWidthDraft, setGridWidthDraft] = useState<string>(image.grid_width?.toString() ?? '')
  const [gridHeightDraft, setGridHeightDraft] = useState<string>(
    image.grid_height?.toString() ?? '',
  )

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
    setEditingSV(false)
    setVariantSearch('')
    setSceneTypeFilter('all')
    setVariantFilters([])
    setGridWidthDraft(src.grid_width?.toString() ?? '')
    setGridHeightDraft(src.grid_height?.toString() ?? '')
    if (scrollContainerRef.current) scrollContainerRef.current.scrollTop = 0
    // image.id is the correct dep — displayImage/image body is intentionally not tracked here
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [image.id])

  // Sync drafts when fresh image data arrives (e.g. after a patch succeeds)
  useEffect(() => {
    if (!editingName) setNameDraft(displayImage?.name ?? '')
    setGridWidthDraft(displayImage?.grid_width?.toString() ?? '')
    setGridHeightDraft(displayImage?.grid_height?.toString() ?? '')
    // editingName/editingSV intentionally omitted: adding them would overwrite in-progress edits
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    displayImage?.name,
    displayImage?.subgroup,
    displayImage?.grid_width,
    displayImage?.grid_height,
  ])

  // Keyboard shortcuts — skip when any input/select/textarea is focused
  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if (editingName || editingSV) return
      const target = e.target as HTMLElement
      if (
        target.tagName === 'INPUT' ||
        target.tagName === 'SELECT' ||
        target.tagName === 'TEXTAREA'
      )
        return
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
    queryClient.invalidateQueries({ queryKey: ['scenes', image.id] })
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
    mutationFn: (payload: Parameters<typeof imageApi.patch>[1]) =>
      imageApi.patch(image.id, payload),
    onSuccess: (updated) => {
      queryClient.setQueryData(['image', image.id], updated)
      queryClient.invalidateQueries({ queryKey: ['scenes'] })
      queryClient.invalidateQueries({ queryKey: ['search'] })
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

  const deleteMutation = useMutation({
    mutationFn: () => imageApi.delete(image.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['search'] })
      queryClient.invalidateQueries({ queryKey: ['scenes'] })
      setConfirmingDelete(false)
      onDelete?.(image.id)
    },
  })

  // ── Derived data ──────────────────────────────────────────────────────────
  const img = displayImage ?? image

  // Build tag vocabulary from full category list (not facets) so new vocabulary
  // values with zero images are still selectable in the tag picker.
  const tagVocab = useMemo(
    (): ParsedTagVocab[] => (tagCategories ? parseTagVocabulary(tagCategories) : []),
    [tagCategories],
  )

  // Convert Image tags → TagData for TagPicker deduplication
  const existingTagData = useMemo(
    (): TagData[] =>
      (img.tags ?? []).map((t) => ({
        category: t.category,
        value: t.value,
        confidence: t.confidence,
        source: t.source,
      })),
    [img.tags],
  )

  // Unique subgroups across the loaded variant group (datalist suggestions)
  const existingSubgroups = useMemo(
    () =>
      [
        ...new Set((scenes ?? []).map((v) => v.subgroup).filter((sv): sv is string => sv != null)),
      ].sort(),
    [scenes],
  )

  // Filter options derived from the loaded variant list
  const sceneFilterGroups = useMemo((): FilterOptionGroup[] => {
    if (!scenes || scenes.length <= 1) return []
    const groups: FilterOptionGroup[] = []

    // Sub-scenes
    const subVariants = [
      ...new Set(scenes.map((v) => v.subgroup).filter((sv): sv is string => sv != null)),
    ].sort()
    if (subVariants.length > 0) {
      groups.push({
        id: 'subgroup',
        label: 'Variant',
        type: 'subgroup',
        options: subVariants.map((sv) => ({
          filterValue: sv,
          label: sv,
          filterLabel: sv,
          count: scenes.filter((v) => v.subgroup === sv).length,
        })),
      })
    }

    // Media type (image vs video)
    const mediaTypes = [...new Set(scenes.map((v) => v.media_type ?? 'image'))]
    if (mediaTypes.length > 1) {
      groups.push({
        id: 'media_type',
        label: 'Media',
        type: 'media_type',
        options: mediaTypes.map((m) => ({
          filterValue: m,
          label: m === 'image' ? 'Images' : m === 'video' ? 'Videos' : m,
          filterLabel: `media: ${m === 'image' ? 'Images' : m === 'video' ? 'Videos' : m}`,
          count: scenes.filter((v) => (v.media_type ?? 'image') === m).length,
        })),
      })
    }

    // Tag categories present across scenes
    const tagMap = new Map<string, Map<string, number>>()
    for (const v of scenes) {
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
  }, [scenes])

  const hasMixedSceneTypes = useMemo(() => {
    if (!scenes || scenes.length <= 1) return false
    return new Set(scenes.map((v) => v.image_type ?? 'battlemap')).size > 1
  }, [scenes])

  const filteredScenes = useMemo(() => {
    let result = scenes ?? []

    if (sceneSearch.trim()) {
      const q = sceneSearch.toLowerCase()
      result = result.filter(
        (v) =>
          v.name.toLowerCase().includes(q) ||
          v.subgroup?.toLowerCase().includes(q) ||
          filenameStem(v.filename).toLowerCase().includes(q),
      )
    }

    if (sceneTypeFilter !== 'all') {
      result = result.filter((v) => (v.image_type ?? 'battlemap') === sceneTypeFilter)
    }

    const includes = sceneFilters.filter((f) => !f.exclude)
    const excludes = sceneFilters.filter((f) => f.exclude)
    if (includes.length) result = result.filter((v) => includes.every((f) => matchesFilter(v, f)))
    if (excludes.length) result = result.filter((v) => !excludes.some((f) => matchesFilter(v, f)))

    return result
  }, [scenes, sceneSearch, sceneTypeFilter, sceneFilters])

  const sceneSections = useMemo(
    () => (filteredScenes.length > 1 ? partitionBySubgroup(filteredScenes) : []),
    [filteredScenes],
  )

  const hasScenes = scenes && scenes.length > 1
  // True when there are dimensions to filter on (not just whether filters are active)
  const hasFilterableData = sceneFilterGroups.length > 0
  const hasActiveFilters = sceneFilters.length > 0

  // ── Handlers ─────────────────────────────────────────────────────────────
  const handleSceneClick = (variant: Image) => {
    preserveStateRef.current = true
    onImageChange?.(variant)
  }

  const handleDownload = async () => {
    setDownloading(true)
    try {
      const resp = await fetch(getImageUrl(img))
      const blob = await resp.blob()
      const objectUrl = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = objectUrl
      a.download = buildDownloadFilename(img)
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(objectUrl)
    } catch (err) {
      console.error('Download failed', err)
    } finally {
      setDownloading(false)
    }
  }

  const handleDownloadGroup = async () => {
    if (!img.group_id) return
    setDownloadingGroup(true)
    try {
      const resp = await fetch(getGroupDownloadUrl(img.group_id))
      const blob = await resp.blob()
      const objectUrl = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = objectUrl
      a.download = `${img.group_name ?? 'Group'}.zip`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(objectUrl)
    } catch (err) {
      console.error('Group download failed', err)
    } finally {
      setDownloadingGroup(false)
    }
  }

  const saveName = () => {
    const trimmed = nameDraft.trim()
    if (trimmed && trimmed !== img.name) renameMutation.mutate(trimmed)
    else setEditingName(false)
  }

  const handleNameKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') saveName()
    if (e.key === 'Escape') {
      setNameDraft(img.name)
      setEditingName(false)
    }
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

          {img.media_type === 'video' ? (
            <video
              key={img.id}
              src={getImageUrl(img)}
              controls
              autoPlay
              loop
              className="max-h-full max-w-full object-contain shadow-2xl shadow-black/60"
            />
          ) : (
            <img
              src={getImageUrl(img)}
              alt={img.name}
              className="max-h-full max-w-full object-contain shadow-2xl shadow-black/60"
            />
          )}
          {onPrevious && (
            <button
              onClick={(e) => {
                e.stopPropagation()
                onPrevious()
              }}
              className="absolute left-3 top-1/2 -translate-y-1/2 h-10 w-10 rounded-full bg-black/50 hover:bg-black/75 text-white/80 hover:text-white flex items-center justify-center transition-all"
            >
              <ChevronLeft className="h-5 w-5" />
            </button>
          )}
          {onNext && (
            <button
              onClick={(e) => {
                e.stopPropagation()
                onNext()
              }}
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

          {/* ── Image info (fixed — stays visible while scenes scroll) ── */}
          <div className="px-4 pt-3 pb-2 shrink-0 border-b border-border/30">
            {/* Controls row: group actions (left) · image actions + close (right) */}
            <div className="flex items-center justify-between mb-1.5">
              <div className="flex items-center gap-3">
                {img.group_id !== null && onEditGroup && (
                  <button
                    onClick={() => onEditGroup(img.group_id!)}
                    className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
                  >
                    <Edit className="h-3.5 w-3.5" />
                    Edit group
                  </button>
                )}
                {img.group_id !== null && (
                  <button
                    onClick={handleDownloadGroup}
                    disabled={downloadingGroup}
                    className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors disabled:opacity-40"
                  >
                    <FolderDown className="h-3.5 w-3.5" />
                    Download group
                  </button>
                )}
              </div>
              <div className="flex items-center gap-0.5">
                <button
                  onClick={handleDownload}
                  disabled={downloading}
                  title="Download image"
                  className="h-7 w-7 rounded flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors disabled:opacity-40"
                >
                  <Download className="h-4 w-4" />
                </button>
                <button
                  onClick={() => setConfirmingDelete(true)}
                  title="Delete image"
                  className="h-7 w-7 rounded flex items-center justify-center text-muted-foreground hover:text-destructive hover:bg-destructive/10 transition-colors"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
                <div className="w-px h-4 bg-border/40 mx-0.5" />
                <button
                  onClick={onClose}
                  title="Close"
                  className="h-7 w-7 rounded flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
            </div>

            {/* Group name — shown when the image belongs to a named group */}
            {img.group_name && img.group_name !== img.name && (
              <p className="font-display text-2xl font-semibold text-muted-foreground truncate mb-0.5">
                {img.group_name}
              </p>
            )}

            {/* Name (inline-editable) */}
            <div className="group/name flex items-start gap-2 mb-0.5">
              {editingName ? (
                <input
                  autoFocus
                  value={nameDraft}
                  onChange={(e) => setNameDraft(e.target.value)}
                  onBlur={saveName}
                  onKeyDown={handleNameKeyDown}
                  className="font-display text-2xl font-semibold bg-transparent border-b border-primary/70 focus:outline-none text-foreground flex-1 min-w-0 pb-px"
                />
              ) : (
                <h2
                  className="font-display text-2xl font-semibold text-foreground cursor-text flex-1 min-w-0 leading-tight"
                  onClick={() => {
                    setNameDraft(img.name)
                    setEditingName(true)
                  }}
                  title="Click to rename"
                >
                  {img.name}
                </h2>
              )}
              {!editingName && (
                <button
                  onClick={() => {
                    setNameDraft(img.name)
                    setEditingName(true)
                  }}
                  className="opacity-0 group-hover/name:opacity-60 hover:!opacity-100 transition-opacity mt-1 text-muted-foreground shrink-0"
                  title="Rename"
                >
                  <Pencil className="h-3.5 w-3.5" />
                </button>
              )}
            </div>

            {/* Author */}
            <p className="text-sm text-muted-foreground">by {img.author}</p>

            {/* File metadata — filename, dimensions, size */}
            <p
              className="text-[10px] text-muted-foreground/40 font-mono truncate mt-1"
              title={img.filename}
            >
              {filenameStem(img.filename)}
            </p>
            <p className="text-[10px] text-muted-foreground/40 mb-3">
              {img.width}×{img.height} · {(img.file_size / 1024 / 1024).toFixed(1)} MB
            </p>

            {/* Sub-variant — inline editable property row */}
            <div className="group/sv relative flex items-center gap-2 mb-2 min-w-0">
              <span className="text-[10px] uppercase tracking-wider text-muted-foreground/60 w-[72px] shrink-0">
                Subgroup
              </span>
              <div className="relative flex-1 min-w-0">
                <button
                  onClick={() => !editingSV && setEditingSV(true)}
                  className="w-full h-6 px-2 text-left text-xs bg-secondary border border-border rounded flex items-center hover:border-primary/40 transition-colors"
                  title={img.subgroup ?? undefined}
                >
                  {img.subgroup ? (
                    <span className="text-foreground/80 capitalize truncate pr-3">
                      {img.subgroup}
                    </span>
                  ) : (
                    <span className="text-muted-foreground/30 italic">—</span>
                  )}
                </button>
                {img.subgroup && (
                  <button
                    onClick={() => patchMutation.mutate({ subgroup: null })}
                    className="absolute right-1 top-1/2 -translate-y-1/2 z-10 opacity-0 group-hover/sv:opacity-40 hover:!opacity-100 transition-opacity text-muted-foreground"
                    title="Clear subgroup"
                  >
                    <X className="h-3 w-3" />
                  </button>
                )}
                <SubgroupDropdown
                  isOpen={editingSV}
                  existingSubgroups={existingSubgroups}
                  initialValue={img.subgroup ?? ''}
                  onCommit={(val) => {
                    patchMutation.mutate({ subgroup: val || null })
                    setEditingSV(false)
                  }}
                  onCancel={() => setEditingSV(false)}
                />
              </div>
            </div>

            {/* Image type toggle */}
            <div className="flex items-center gap-2 mb-2">
              <span className="text-[10px] uppercase tracking-wider text-muted-foreground/60 w-[72px] shrink-0">
                Type
              </span>
              <div className="inline-flex rounded border border-border p-px bg-secondary/50">
                <button
                  onClick={() => patchMutation.mutate({ image_type: 'battlemap' })}
                  disabled={patchMutation.isPending}
                  className={`px-2 py-0.5 text-[11px] rounded-sm transition-colors ${
                    img.image_type !== 'scene'
                      ? 'bg-primary/20 text-primary font-medium'
                      : 'text-muted-foreground/60 hover:text-muted-foreground'
                  }`}
                >
                  Map
                </button>
                <button
                  onClick={() => patchMutation.mutate({ image_type: 'scene' })}
                  disabled={patchMutation.isPending}
                  className={`px-2 py-0.5 text-[11px] rounded-sm transition-colors ${
                    img.image_type === 'scene'
                      ? 'bg-primary/20 text-primary font-medium'
                      : 'text-muted-foreground/60 hover:text-muted-foreground'
                  }`}
                >
                  Scene
                </button>
              </div>
            </div>

            {/* Gridded toggle + optional grid size inputs (hidden for scenes) */}
            {img.image_type !== 'scene' && (
              <div className="flex items-center gap-2 mb-2">
                <span className="text-[10px] uppercase tracking-wider text-muted-foreground/60 w-[72px] shrink-0">
                  Grid
                </span>
                <div className="flex items-center gap-2 flex-1 min-w-0">
                  <GridToggle
                    gridded={img.gridded ?? null}
                    gridType={img.grid_type ?? null}
                    onChange={(gridded, gridType) =>
                      patchMutation.mutate({ gridded, grid_type: gridType })
                    }
                    disabled={patchMutation.isPending}
                  />
                  {img.gridded === true && (
                    <div className="flex items-center gap-1 text-xs text-muted-foreground">
                      <input
                        type="number"
                        value={gridWidthDraft}
                        onChange={(e) => setGridWidthDraft(e.target.value)}
                        onBlur={() => {
                          const w = parseInt(gridWidthDraft) || null
                          if (w !== img.grid_width) patchMutation.mutate({ grid_width: w })
                        }}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') (e.target as HTMLInputElement).blur()
                        }}
                        placeholder="W"
                        min={1}
                        className="w-11 bg-secondary border border-border rounded px-1.5 py-0.5 text-foreground text-center placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary/40 text-[11px] [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none"
                      />
                      <span className="text-[11px]">×</span>
                      <input
                        type="number"
                        value={gridHeightDraft}
                        onChange={(e) => setGridHeightDraft(e.target.value)}
                        onBlur={() => {
                          const h = parseInt(gridHeightDraft) || null
                          if (h !== img.grid_height) patchMutation.mutate({ grid_height: h })
                        }}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') (e.target as HTMLInputElement).blur()
                        }}
                        placeholder="H"
                        min={1}
                        className="w-11 bg-secondary border border-border rounded px-1.5 py-0.5 text-foreground text-center placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary/40 text-[11px] [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none"
                      />
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* Divider + color swatches + tags */}
            <div className="border-t border-border/30 pt-3 mt-1">
              {img.colors && img.colors.length > 0 && (
                <div className="flex gap-1 mb-2">
                  {img.colors
                    .sort((a, b) => a.color_order - b.color_order)
                    .map((color) => (
                      <div
                        key={color.id}
                        className="h-5 w-5 rounded-full ring-1 ring-white/15 shadow-sm"
                        style={{ backgroundColor: color.color_hex }}
                        title={`${color.color_hex} (${(color.percentage * 100).toFixed(1)}%)`}
                      />
                    ))}
                </div>
              )}

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
                  onAdd={(tag) =>
                    addTagMutation.mutate({ category: tag.category, value: tag.value })
                  }
                />
              </div>
            </div>
          </div>

          {/* ── Variants section (only this scrolls) ── */}
          {hasScenes && (
            <div ref={scrollContainerRef} className="flex-1 min-h-0 overflow-y-auto">
              {/* Sticky header: label + search + filter button */}
              <div className="sticky top-0 z-10 bg-card border-b border-border/30">
                <div className="px-4 py-2 flex items-center gap-2">
                  <span className="text-sm font-semibold shrink-0">
                    Scenes
                    <span className="ml-1.5 text-xs font-normal text-muted-foreground">
                      ({filteredScenes.length}
                      {(sceneSearch || sceneTypeFilter !== 'all' || hasActiveFilters) && scenes
                        ? `/${scenes.length}`
                        : ''}
                      )
                    </span>
                  </span>

                  {/* Search */}
                  <div className="relative flex-1">
                    <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3 w-3 text-muted-foreground pointer-events-none" />
                    <input
                      value={sceneSearch}
                      onChange={(e) => setVariantSearch(e.target.value)}
                      placeholder="Filter…"
                      className={`w-full h-6 pl-6 text-xs bg-secondary border border-border rounded focus:outline-none focus:ring-1 focus:ring-primary/40 text-foreground placeholder:text-muted-foreground ${
                        sceneSearch || sceneTypeFilter !== 'all' ? 'pr-6' : 'pr-2'
                      }`}
                    />
                    {(sceneSearch || sceneTypeFilter !== 'all') && (
                      <button
                        onClick={() => {
                          setVariantSearch('')
                          setSceneTypeFilter('all')
                        }}
                        className="absolute right-1.5 top-1/2 -translate-y-1/2 text-muted-foreground/40 hover:text-muted-foreground transition-colors"
                      >
                        <X className="h-3 w-3" />
                      </button>
                    )}
                  </div>

                  {/* Type toggle — only when group has mixed types */}
                  {hasMixedSceneTypes && (
                    <div className="inline-flex rounded border border-border overflow-hidden shrink-0">
                      {(
                        [
                          ['All', 'all'],
                          ['Maps', 'battlemap'],
                          ['Scenes', 'scene'],
                        ] as const
                      ).map(([label, val]) => (
                        <button
                          key={val}
                          onClick={() => setSceneTypeFilter(val)}
                          className={`px-1.5 py-0.5 text-[10px] transition-colors ${
                            sceneTypeFilter === val
                              ? 'bg-secondary text-foreground font-medium'
                              : 'text-muted-foreground/60 hover:text-muted-foreground hover:bg-secondary/50'
                          }`}
                        >
                          {label}
                        </button>
                      ))}
                    </div>
                  )}

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
                        title={hasFilterableData ? 'Filter scenes' : 'No filterable dimensions'}
                      >
                        <SlidersHorizontal className="h-3 w-3" />
                        {hasActiveFilters && (
                          <span className="absolute -top-1 -right-1 h-3.5 w-3.5 rounded-full bg-primary text-[9px] font-bold text-primary-foreground flex items-center justify-center">
                            {sceneFilters.length}
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
                          groups={sceneFilterGroups}
                          activeFilters={sceneFilters}
                          onFiltersChange={setVariantFilters}
                        />
                      </PopoverContent>
                    )}
                  </Popover>
                </div>

                {/* Active filter chips */}
                {hasActiveFilters && (
                  <div className="px-4 pb-2">
                    <FilterChipList filters={sceneFilters} onFiltersChange={setVariantFilters} />
                  </div>
                )}
              </div>

              {/* Variant grid */}
              <div className="px-4 pt-3 pb-4">
                {filteredScenes.length === 0 ? (
                  <p className="text-xs text-muted-foreground text-center py-6">No scenes match</p>
                ) : (
                  sceneSections.map((section) => (
                    <div key={section.label} className="mb-3 last:mb-0">
                      {sceneSections.length > 1 && (
                        <p className="text-[11px] font-medium text-muted-foreground mb-2 uppercase tracking-wider">
                          {section.label}
                        </p>
                      )}
                      <div className="grid grid-cols-2 gap-2">
                        {section.images.map((variant) => (
                          <SceneTile
                            key={variant.id}
                            image={variant}
                            isActive={variant.id === img.id}
                            primaryText={variant.name}
                            secondaryText={
                              variant.gridded && variant.image_type !== 'scene'
                                ? variant.grid_width && variant.grid_height
                                  ? `${variant.grid_width}×${variant.grid_height}`
                                  : 'Grid'
                                : undefined
                            }
                            onClick={() => handleSceneClick(variant)}
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

      <ConfirmDialog
        open={confirmingDelete}
        onOpenChange={setConfirmingDelete}
        title="Delete Image"
        description={
          <>
            Permanently delete <strong>{img.name}</strong>? This cannot be undone.
          </>
        }
        confirmLabel="Delete"
        onConfirm={() => deleteMutation.mutate()}
        isLoading={deleteMutation.isPending}
      />
    </div>
  )
}

// ── Helpers ───────────────────────────────────────────────────────────────────

interface SceneSection {
  label: string
  images: Image[]
}

function matchesFilter(v: Image, f: ActiveFilter): boolean {
  if (f.type === 'subgroup') return v.subgroup === f.value
  if (f.type === 'tag') {
    const idx = f.value.indexOf(':')
    const cat = f.value.slice(0, idx)
    const val = f.value.slice(idx + 1)
    return v.tags?.some((t) => t.category === cat && t.value === val) ?? false
  }
  if (f.type === 'media_type') return (v.media_type ?? 'image') === f.value
  return true
}

function partitionBySubgroup(scenes: Image[]): SceneSection[] {
  const groups = new Map<string, Image[]>()
  const order: string[] = []

  for (const v of scenes) {
    const key = v.subgroup || 'Other'
    if (!groups.has(key)) {
      groups.set(key, [])
      order.push(key)
    }
    groups.get(key)!.push(v)
  }

  if (order.length <= 1) return [{ label: order[0] ?? 'All scenes', images: scenes }]
  return order.map((label) => ({ label, images: groups.get(label)! }))
}

function filenameStem(filename: string): string {
  return filename.replace(/\.[^.]+$/, '')
}

function sanitizeSegment(s: string): string {
  // Replace filesystem-unsafe characters and path separators with a space
  return s
    .replace(/[/\\:*?"<>|]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

function buildDownloadFilename(img: Image): string {
  const parts: string[] = []

  if (img.group_name && img.group_name !== img.name) parts.push(sanitizeSegment(img.group_name))
  if (img.subgroup) parts.push(sanitizeSegment(img.subgroup))
  parts.push(sanitizeSegment(img.name))

  if (img.gridded === true) {
    const label = img.grid_type === 'hex' ? 'Hex' : 'Grid'
    const dims = img.grid_width && img.grid_height ? ` ${img.grid_width}x${img.grid_height}` : ''
    parts.push(`${label}${dims}`)
  } else {
    parts.push('No Grid')
  }

  const ext = img.filename.match(/\.[^.]+$/)?.[0] ?? ''
  return parts.join(' - ') + ext
}
