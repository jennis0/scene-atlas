import { useEffect, useMemo, useRef } from 'react'
import { Upload, LayoutGrid, Layers, Tag, Settings, Sun, Moon, Loader2 } from 'lucide-react'
import { BrandMark } from '@/components/brand/BrandMark'
import { GalleryFilterPanel } from '@/components/GalleryFilterPanel'
import { GallerySearchBar } from '@/components/GallerySearchBar'
import { GalleryResultsBar } from '@/components/GalleryResultsBar'
import { Button } from '@/components/ui/button'
import { useTheme } from '@/contexts/ThemeContext'
import { isApp } from '@/lib/appMode'
import { useCompactHeader } from '@/lib/compactLayout'
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
  const compact = useCompactHeader()
  const tabStrip = useMemo(() => {
    const typeCounts = Object.fromEntries(
      (facets?.image_types ?? []).map((t) => [t.value, t.count]),
    )
    const total = Object.values(typeCounts).reduce((s, n) => s + n, 0)
    const tabs = [
      { value: 'all' as ImageTypeFilter, label: 'All', count: total },
      {
        value: 'battlemap' as ImageTypeFilter,
        label: 'Maps',
        count: typeCounts['battlemap'] ?? 0,
      },
      {
        value: 'scene' as ImageTypeFilter,
        label: 'Scenes',
        count: typeCounts['scene'] ?? 0,
      },
    ]
    return (
      <div
        role="group"
        aria-label="Image type"
        className={
          compact
            ? `flex items-stretch self-stretch ${isApp ? 'no-drag-region' : ''}`
            : 'flex items-stretch border-b border-border/60'
        }
      >
        {tabs.map(({ value, label, count }) => (
          <button
            key={value}
            aria-pressed={imageType === value}
            onClick={() => handleImageTypeChange(value)}
            className={`flex items-center gap-2 px-3 first:pl-0 py-2.5 text-sm font-medium border-b-2 transition-colors
              ${
                imageType === value
                  ? 'border-primary text-foreground'
                  : 'border-transparent text-muted-foreground hover:text-foreground'
              }`}
          >
            {label}
            {count > 0 && (
              <span
                className={`text-3xs font-normal px-1.5 py-px rounded-full transition-colors
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
  }, [facets, imageType, handleImageTypeChange, compact])

  return (
    <header className="border-b border-border/70 bg-card">
      {/* Windows/Linux: draggable titlebar strip matching the OS overlay zone */}
      {needsOverlayPadding && <div className="h-8 drag-region" />}
      <div className={`container mx-auto px-4 ${isMac ? 'pl-20' : ''}`}>
        <div
          className={`${compact ? '' : needsOverlayPadding ? 'pt-2 pb-2' : 'pt-4 pb-3'} flex flex-wrap gap-x-4 gap-y-2 items-center justify-between border-b border-border/70 ${isApp ? 'drag-region' : ''}`}
        >
          <div className={compact ? 'flex items-stretch gap-x-6 self-stretch' : ''}>
            <h1
              className={`flex items-center gap-[0.45em] font-wordmark font-medium tracking-wide text-foreground ${compact ? 'text-xl self-center' : 'text-2xl'}`}
            >
              <BrandMark className="h-[1.05em] w-auto shrink-0" />
              Scene Atlas
            </h1>
            {compact && tabStrip}
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
                  ? 'Waiting for the search model to load\u2026'
                  : 'Import images'
              }
              className="gap-1.5"
            >
              <Upload className="h-3.5 w-3.5" />
              Import
            </Button>
          </div>
        </div>

        {!compact && tabStrip}

        <div
          className={`flex flex-wrap items-center gap-2 ${compact ? 'py-2' : 'md:flex-nowrap pt-3 pb-3'}`}
        >
          <GallerySearchBar search={search} inputRef={searchRef} />

          {embeddingStatus === 'loading' && (
            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-warning/15 text-warning shrink-0">
              <Loader2 className="h-3 w-3 animate-spin" />
              Search model loading&hellip;
            </span>
          )}
          {embeddingStatus === 'error' && (
            <span
              className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-destructive/15 text-destructive shrink-0 cursor-help"
              title={embeddingError ?? 'Unknown error'}
            >
              Search model unavailable
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

          {compact && (
            <>
              <div className="h-5 w-px bg-border/60 shrink-0 mx-0.5" />
              <GalleryResultsBar
                search={search}
                displayImageCount={displayImageCount}
                onOpenMassEdit={onOpenMassEdit}
                tileWidth={tileWidth}
                onTileWidthChange={onTileWidthChange}
                inline={compact}
              />
            </>
          )}
        </div>

        {!compact && (
          <GalleryResultsBar
            search={search}
            displayImageCount={displayImageCount}
            onOpenMassEdit={onOpenMassEdit}
            tileWidth={tileWidth}
            onTileWidthChange={onTileWidthChange}
            inline={compact}
          />
        )}
      </div>
    </header>
  )
}
