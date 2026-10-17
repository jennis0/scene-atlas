import { AlignLeft, Search, Sparkles, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { MAX_SEARCH_LENGTH } from '@/lib/constants'
import type { UseGallerySearchReturn } from '@/hooks/useGallerySearch'

/** The search field and its Search button, joined into one control. */
export function GallerySearchBar({ search }: { search: UseGallerySearchReturn }) {
  const {
    searchInput,
    setSearchInput,
    imageType,
    isSemantic,
    isTextOnly,
    isSearching,
    handleSubmit,
  } = search
  return (
    <form
      role="search"
      onSubmit={handleSubmit}
      className="focus-ring-within-input rounded-md flex basis-full md:basis-auto flex-1 min-w-0"
    >
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
          aria-label="Search the library"
          placeholder={`Search ${imageType === 'all' ? 'scenes' : imageType === 'battlemap' ? 'maps' : 'scenes'}\u2026  "quotes" for exact phrase, ~ visual, = keyword`}
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
          maxLength={MAX_SEARCH_LENGTH}
          className="h-10 w-full pl-9 pr-8 rounded-r-none border-r-0 focus-visible:outline-none"
        />
        {searchInput && (
          <button
            type="button"
            onClick={search.clearSearch}
            aria-label="Clear search"
            className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        )}
      </div>

      <Button type="submit" disabled={isSearching} className="rounded-l-none h-10 shrink-0 px-5">
        {isSearching ? 'Searching\u2026' : 'Search'}
      </Button>
    </form>
  )
}
