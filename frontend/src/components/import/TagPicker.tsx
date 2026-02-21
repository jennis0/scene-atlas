import { useState, useEffect, useRef, useMemo } from 'react'
import { Plus, ChevronLeft, Search, X } from 'lucide-react'
import type { TagData } from '@/types'
import type { ParsedTagVocab } from './types'
import { useGetTagColor } from '@/contexts/TagColorContext'

interface TagPickerProps {
  vocab: ParsedTagVocab[]
  existingTags: TagData[]
  onAdd: (tag: TagData) => void
}

export function TagPicker({ vocab, existingTags, onAdd }: TagPickerProps) {
  const getTagColor = useGetTagColor()
  const [open, setOpen] = useState(false)
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const handleClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false)
        setSelectedCategory(null)
        setSearch('')
      }
    }
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { setOpen(false); setSelectedCategory(null); setSearch('') }
    }
    document.addEventListener('mousedown', handleClickOutside)
    document.addEventListener('keydown', handleEscape)
    return () => {
      document.removeEventListener('mousedown', handleClickOutside)
      document.removeEventListener('keydown', handleEscape)
    }
  }, [open])

  const existingKeys = new Set(existingTags.map((t) => `${t.category}:${t.value}`))
  const selectedVocab = vocab.find((v) => v.category === selectedCategory)
  const availableValues = selectedVocab
    ? selectedVocab.values.filter((v) => !existingKeys.has(`${selectedCategory}:${v}`))
    : []

  const searchResults = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return []
    const results: Array<{ category: string; value: string }> = []
    for (const v of vocab) {
      for (const val of v.values) {
        if (existingKeys.has(`${v.category}:${val}`)) continue
        if (val.toLowerCase().includes(q) || v.category.toLowerCase().includes(q)) {
          results.push({ category: v.category, value: val })
        }
      }
    }
    return results
  }, [search, vocab, existingKeys]) // eslint-disable-line react-hooks/exhaustive-deps

  const handleAdd = (category: string, value: string) => {
    onAdd({ category, value, confidence: 1.0, source: 'manual' })
    setOpen(false)
    setSelectedCategory(null)
    setSearch('')
  }

  const isSearching = search.trim().length > 0

  return (
    <div className="relative inline-block" ref={containerRef}>
      <button
        onClick={() => { setOpen(!open); setSelectedCategory(null); setSearch('') }}
        className="inline-flex items-center gap-1 rounded-full border border-dashed border-border/50 px-2 py-0.5 text-xs text-muted-foreground hover:text-foreground hover:border-border hover:bg-secondary/50 transition-all"
      >
        <Plus className="h-3 w-3" />
        Tag
      </button>

      {open && (
        <div className="absolute left-0 top-full mt-1.5 z-50 w-[220px] rounded-xl border border-border bg-card shadow-2xl shadow-black/40 overflow-hidden flex flex-col">
          {/* Search input */}
          <div className="px-2 pt-2 pb-1.5 border-b border-border/50 shrink-0">
            <div className="relative">
              <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3 w-3 text-muted-foreground/50 pointer-events-none" />
              <input
                autoFocus
                value={search}
                onChange={(e) => { setSearch(e.target.value); setSelectedCategory(null) }}
                placeholder="Search tags…"
                className="w-full h-6 pl-6 pr-5 text-xs bg-secondary border border-border rounded focus:outline-none focus:ring-1 focus:ring-primary/40 text-foreground placeholder:text-muted-foreground"
                onKeyDown={(e) => {
                  e.stopPropagation()
                  if (e.key === 'Enter' && searchResults.length === 1) {
                    handleAdd(searchResults[0].category, searchResults[0].value)
                  }
                }}
              />
              {search && (
                <button
                  onClick={() => setSearch('')}
                  className="absolute right-1.5 top-1/2 -translate-y-1/2 text-muted-foreground/50 hover:text-muted-foreground transition-colors"
                >
                  <X className="h-3 w-3" />
                </button>
              )}
            </div>
          </div>

          {/* Body */}
          <div className="overflow-y-auto max-h-[240px] py-1">
            {isSearching ? (
              searchResults.length === 0 ? (
                <p className="px-3 py-3 text-xs text-muted-foreground text-center">No matching tags</p>
              ) : (
                searchResults.map(({ category, value }) => {
                  const color = getTagColor(category)
                  return (
                    <button
                      key={`${category}:${value}`}
                      onClick={() => handleAdd(category, value)}
                      className="flex w-full items-center gap-2 px-3 py-1.5 text-sm hover:bg-secondary transition-colors text-left"
                    >
                      <span className={`w-2 h-2 rounded-full shrink-0 ${color.dot}`} />
                      <span className="text-foreground capitalize flex-1 truncate">{value}</span>
                      <span className="text-[10px] text-muted-foreground/50 capitalize shrink-0">{category}</span>
                    </button>
                  )
                })
              )
            ) : !selectedCategory ? (
              <>
                <div className="px-3 pt-1 pb-1.5 text-[10px] font-semibold text-muted-foreground uppercase tracking-widest">
                  Pick category
                </div>
                {vocab.map((v) => {
                  const color = getTagColor(v.category)
                  return (
                    <button
                      key={v.category}
                      onClick={() => setSelectedCategory(v.category)}
                      className="flex w-full items-center gap-2 px-3 py-1.5 text-sm hover:bg-secondary transition-colors text-left group"
                    >
                      <span className={`w-2 h-2 rounded-full shrink-0 ${color.dot}`} />
                      <span className="capitalize text-foreground">{v.category}</span>
                      <span className="ml-auto text-xs text-muted-foreground/60">{v.values.length}</span>
                    </button>
                  )
                })}
              </>
            ) : (
              <>
                <button
                  onClick={() => setSelectedCategory(null)}
                  className="flex items-center gap-1.5 px-3 py-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors w-full"
                >
                  <ChevronLeft className="h-3 w-3" />
                  <span className="capitalize">{selectedCategory}</span>
                </button>
                <div className="h-px bg-border mx-2" />
                <div className="py-1">
                  {availableValues.length === 0 ? (
                    <div className="px-3 py-3 text-xs text-muted-foreground italic text-center">All values applied</div>
                  ) : (
                    availableValues.map((value) => (
                      <button
                        key={value}
                        onClick={() => handleAdd(selectedCategory, value)}
                        className="flex w-full items-center px-3 py-1.5 text-sm text-foreground hover:bg-primary/10 hover:text-primary transition-colors text-left capitalize"
                      >
                        {value}
                      </button>
                    ))
                  )}
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
