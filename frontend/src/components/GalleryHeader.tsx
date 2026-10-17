import { useEffect, useMemo, useRef } from 'react'
import {
  Upload,
  LayoutGrid,
  Layers,
  Tag,
  Settings,
  Compass,
  Map,
  Mountain,
  Sun,
  Moon,
  Loader2,
} from 'lucide-react'
import { GalleryFilterPanel } from '@/components/GalleryFilterPanel'
import { GallerySearchBar } from '@/components/GallerySearchBar'
import { GalleryResultsBar } from '@/components/GalleryResultsBar'
import { Button } from '@/components/ui/button'
import { useTheme } from '@/contexts/ThemeContext'
import { isApp } from '@/lib/appMode'
import type { UseGallerySearchReturn } from '@/hooks/useGallerySearch'
import type { EmbeddingStatus } from '@/hooks/useEmbeddingStatus'
import type { ImageTypeFilter } from '@/components/import/fileFilter'
import { isAnyDialogOpen } from '@/components/ui/dialogStack'

// Platform helpers for borderless window layout
const isMac = isApp && window.electronAPI?.platform === 'darwin'
const needsOverlayPadding = isApp && !isMac // Windows/Linux titlebar overlay

export interface GalleryHeaderProps {
  search: UseGallerySearchReturn & {
    editAllLoading?: boolean
  }
  embeddingStatus: EmbeddingStatus
  embeddingError?: string
  onOpenImport: () => void
  onOpenTagManagement: () => void
  onOpenSystemInfo: () => void
  onOpenMassEdit: () => void
  displayImageCount: number
  /** Individual-view tile width in px */
  tileWidth: number
  onTileWidthChange: (width: number) => void
}

/** True when a key press should type into whatever has focus, not trigger a shortcut. */
function isTypingTarget(el: EventTarget | null) {
  if (!(el instanceof HTMLElement)) return false
  return el.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName)
}

export function GalleryHeader({
  search,
  embeddingStatus,
  embeddingError,
  onOpenImport,
  onOpenTagManagement,
  onOpenSystemInfo,
  onOpenMassEdit,
  displayImageCount,
  tileWidth,
  onTileWidthChange,
}: GalleryHeaderProps) {
  const { theme, toggleTheme } = useTheme()

  // "/" jumps to search from anywhere on the page, unless something else is being typed in.
  const searchRef = useRef<HTMLInputElement>(null)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== '/' || e.ctrlKey || e.metaKey || e.altKey) return
      if (isTypingTarget(e.target) || isAnyDialogOpen()) return
      e.preventDefault()
      searchRef.current?.focus()
      searchRef.current?.select()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])
  const {
    filters,
    imageType,
    viewMode,
    setViewMode,
    facets,
    handleFiltersChange,
    handleImageTypeChange,
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
      <div
        role="group"
        aria-label="Image type"
        className="-mx-4 px-4 flex items-stretch border-b border-border/60"
      >
        {tabs.map(({ value, label, Icon, count }) => (
          <button
            key={value}
            aria-pressed={imageType === value}
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
    <header className="border-b border-border/70 bg-card">
      {/* Windows/Linux: draggable titlebar strip matching the OS overlay zone */}
      {needsOverlayPadding && <div className="h-8 drag-region" />}
      <div className={`container mx-auto px-4 ${isMac ? 'pl-20' : ''}`}>
        <div
          className={`${needsOverlayPadding ? 'pt-2 pb-2' : 'pt-4 pb-3'} flex flex-wrap gap-x-4 gap-y-2 items-center justify-between border-b border-border/70 ${isApp ? 'drag-region' : ''}`}
        >
          <div>
            <h1 className="font-wordmark text-2xl font-medium tracking-wide text-foreground">
              Scene Atlas
            </h1>
          </div>
          {/* Admin cluster: utility actions (ghost) + gap + primary Import CTA */}
          <div className={`flex items-center gap-1 ${isApp ? 'no-drag-region' : ''}`}>
            <Button
              variant="ghost"
              size="sm"
              onClick={onOpenTagManagement}
              title="Manage tag categories and values"
              aria-label="Manage tags"
              className="gap-1.5 text-muted-foreground hover:text-foreground"
            >
              <Tag className="h-3.5 w-3.5" />
              <span className="hidden sm:inline">Manage Tags</span>
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
            <div className="w-4 shrink-0" />
            <Button
              size="sm"
              onClick={onOpenImport}
              disabled={embeddingStatus === 'loading'}
              title={
                embeddingStatus === 'loading'
                  ? 'Waiting for AI model to finish loading\u2026'
                  : 'Import images'
              }
              className="gap-1.5"
            >
              <Upload className="h-3.5 w-3.5" />
              Import
            </Button>
          </div>
        </div>

        {tabStrip}

        <div className="flex flex-wrap md:flex-nowrap items-center gap-2 pt-3 pb-3">
          <GallerySearchBar search={search} inputRef={searchRef} />

          {embeddingStatus === 'loading' && (
            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300 shrink-0">
              <Loader2 className="h-3 w-3 animate-spin" />
              AI search loading&hellip;
            </span>
          )}
          {embeddingStatus === 'error' && (
            <span
              className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300 shrink-0 cursor-help"
              title={embeddingError ?? 'Unknown error'}
            >
              AI search unavailable
            </span>
          )}

          <GalleryFilterPanel
            filters={filters}
            facets={facets}
            onFiltersChange={handleFiltersChange}
          />

          {/* Thin separator between search tools and view controls */}
          <div className="h-5 w-px bg-border/60 shrink-0 mx-0.5" />

          {/* View mode toggle -- icon buttons, no outer border */}
          <div role="group" aria-label="View" className="flex items-center gap-0.5 shrink-0">
            <button
              aria-pressed={viewMode === 'individual'}
              onClick={() => setViewMode('individual')}
              title="Individual images"
              className={`h-8 w-8 flex items-center justify-center rounded transition-colors
                ${viewMode === 'individual' ? 'bg-secondary text-foreground' : 'text-muted-foreground hover:text-foreground hover:bg-secondary/50'}`}
            >
              <LayoutGrid className="h-4 w-4" />
            </button>
            <button
              aria-pressed={viewMode === 'grouped'}
              onClick={() => setViewMode('grouped')}
              title="Groups"
              className={`h-8 w-8 flex items-center justify-center rounded transition-colors
                ${viewMode === 'grouped' ? 'bg-secondary text-foreground' : 'text-muted-foreground hover:text-foreground hover:bg-secondary/50'}`}
            >
              <Layers className="h-4 w-4" />
            </button>
          </div>
        </div>

        <GalleryResultsBar
          search={search}
          displayImageCount={displayImageCount}
          onOpenMassEdit={onOpenMassEdit}
          tileWidth={tileWidth}
          onTileWidthChange={onTileWidthChange}
        />
      </div>
    </header>
  )
}
