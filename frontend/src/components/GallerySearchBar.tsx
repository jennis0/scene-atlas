import type { RefObject } from 'react'
import { AlignLeft, Search, Sparkles, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { MAX_SEARCH_LENGTH } from '@/lib/constants'
import type { UseGallerySearchReturn } from '@/hooks/useGallerySearch'

/** The search field and its Search button, joined into one control. */
export function GallerySearchBar({
  search,
  inputRef,
}: {
  search: UseGallerySearchReturn
  /** The field "/" focuses from anywhere on the page */
  inputRef?: RefObject<HTMLInputElement>
}) {
  return (
    <form
      role="search"
      onSubmit={search.handleSubmit}
      className="focus-ring-within-input rounded-md flex basis-full md:basis-auto flex-1 min-w-0"
    >
      <div className="relative flex-1 min-w-0">
        <SearchModeIcon semantic={search.isSemantic} textOnly={search.isTextOnly} />
        <Input
          ref={inputRef}
          type="text"
          aria-keyshortcuts="/"
          aria-label="Search the library"
          placeholder={`Search ${search.imageType === 'all' ? 'scenes' : search.imageType === 'battlemap' ? 'maps' : 'scenes'}\u2026  "quotes" for exact phrase, ~ visual, = keyword`}
          value={search.searchInput}
          onChange={(e) => search.setSearchInput(e.target.value)}
          maxLength={MAX_SEARCH_LENGTH}
          className="h-10 w-full pl-9 pr-8 rounded-r-none border-r-0 focus-visible:outline-none"
        />
        {search.searchInput ? <ClearButton onClick={search.clearSearch} /> : <SlashHint />}
      </div>

      <Button
        type="submit"
        variant="secondary"
        disabled={search.isSearching}
        className="rounded-l-none h-10 shrink-0 px-5 border border-border"
      >
        {search.isSearching ? 'Searching\u2026' : 'Search'}
      </Button>
    </form>
  )
}

const ICON_CLASS =
  'absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground pointer-events-none'

/** Shows which kind of search the query will run: visual (~), keyword (=), or both. */
function SearchModeIcon({ semantic, textOnly }: { semantic: boolean; textOnly: boolean }) {
  if (semantic) return <Sparkles className={ICON_CLASS} />
  if (textOnly) return <AlignLeft className={ICON_CLASS} />
  return <Search className={ICON_CLASS} />
}

/** In the empty field: a reminder that "/" jumps here. */
function SlashHint() {
  return (
    <kbd
      aria-hidden="true"
      className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 hidden sm:flex h-5 min-w-5 items-center justify-center rounded border border-border px-1 font-mono text-[11px] text-muted-foreground"
      title="Press / to search"
    >
      /
    </kbd>
  )
}

function ClearButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label="Clear search"
      className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors"
    >
      <X className="h-3.5 w-3.5" />
    </button>
  )
}
