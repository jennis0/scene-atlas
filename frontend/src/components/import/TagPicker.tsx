import { useState, useEffect, useRef, useMemo } from 'react'
import { Plus, ChevronLeft, Search, X } from 'lucide-react'
import type { TagData } from '@/types'
import type { ParsedTagVocab } from './types'
import { useGetTagColor } from '@/contexts/TagColorContext'
import { getCategoryIcon } from '@/lib/categoryIcons'

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
      if (e.key === 'Escape') {
        e.stopImmediatePropagation()
        setOpen(false)
        setSelectedCategory(null)
        setSearch('')
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    document.addEventListener('keydown', handleEscape)
    return () => {
      document.removeEventListener('mousedown', handleClickOutside)
      document.removeEventListener('keydown', handleEscape)
    }
  }, [open])

  const existingKeys = useMemo(
    () => new Set(existingTags.map((t) => `${t.category}:${t.value}`)),
    [existingTags],
  )
  const selectedVocab = vocab.find((v) => v.category === selectedCategory)
  const selectedColor = selectedCategory ? getTagColor(selectedCategory) : null
  const SelectedIcon = selectedVocab ? getCategoryIcon(selectedVocab.icon) : null
  const availableValues = selectedVocab
    ? selectedVocab.values.filter((v) => !existingKeys.has(`${selectedCategory}:${v}`))
    : []

  const searchResults = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return []
    const scored: Array<{ category: string; value: string; score: number }> = []
    for (const v of vocab) {
      const catMatch = v.category.toLowerCase().includes(q)
      for (const val of v.values) {
        if (existingKeys.has(`${v.category}:${val}`)) continue
        const l = val.toLowerCase()
        const aa = (v.aliases[val] ?? []).map((a) => a.toLowerCase())
        let score: number
        if (l === q) score = 5
        else if (l.startsWith(q)) score = 4
        else if (aa.some((a) => a === q)) score = 3
        else if (l.includes(q)) score = 2
        else if (aa.some((a) => a.startsWith(q))) score = 1
        else if (aa.some((a) => a.includes(q))) score = 0
        else if (catMatch) score = -1
        else continue
        scored.push({ category: v.category, value: val, score })
      }
    }
    scored.sort((a, b) => b.score - a.score)
    return scored.map(({ category, value }) => ({ category, value }))
  }, [search, vocab, existingKeys])

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
        onClick={() => {
          setOpen(!open)
          setSelectedCategory(null)
          setSearch('')
        }}
        className="inline-flex items-center gap-1 rounded-full border border-dashed border-border/50 px-2 py-0.5 text-xs text-muted-foreground hover:text-foreground hover:border-border hover:bg-secondary/50 transition-all"
      >
        <Plus className="h-3 w-3" />
        Tag
      </button>

      {open && (
        <div className="absolute left-0 top-full mt-1.5 z-50 w-[12.94rem] rounded-md border border-border bg-card shadow-2xl shadow-shade/40 overflow-hidden flex flex-col">
          <div className="px-2 pt-2 pb-1.5 border-b border-border/50 shrink-0">
            <div className="relative">
              <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3 w-3 text-muted-foreground pointer-events-none" />
              <input
                autoFocus
                value={search}
                onChange={(e) => {
                  setSearch(e.target.value)
                  setSelectedCategory(null)
                }}
                placeholder="Search tags…"
                className="w-full h-6 pl-6 pr-5 text-xs bg-secondary border border-border rounded text-foreground placeholder:text-muted-foreground"
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
                  className="absolute right-1.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-muted-foreground transition-colors"
                >
                  <X className="h-3 w-3" />
                </button>
              )}
            </div>
          </div>

          <div className="overflow-y-auto max-h-[14.12rem] py-1">
            {isSearching ? (
              searchResults.length === 0 ? (
                <p className="px-3 py-3 text-xs text-muted-foreground text-center">
                  No matching tags
                </p>
              ) : (
                searchResults.map(({ category, value }) => {
                  const color = getTagColor(category)
                  return (
                    <button
                      key={`${category}:${value}`}
                      onClick={() => handleAdd(category, value)}
                      className={`flex w-full items-center gap-2 px-3 py-1.5 text-xs ${color.text} hover:bg-primary/10 hover:text-primary transition-colors text-left`}
                    >
                      <span className="capitalize flex-1 truncate">{value}</span>
                      <span className="text-3xs text-muted-foreground capitalize shrink-0">
                        {category}
                      </span>
                    </button>
                  )
                })
              )
            ) : !selectedCategory ? (
              <>
                <div className="section-label px-3 pt-1 pb-1.5">Pick category</div>
                {vocab.map((v) => {
                  const color = getTagColor(v.category)
                  const CatIcon = getCategoryIcon(v.icon)
                  return (
                    <button
                      key={v.category}
                      onClick={() => setSelectedCategory(v.category)}
                      className={`flex w-full items-center gap-2 text-left text-xs border-l-2 ${color.border} text-muted-foreground hover:text-foreground hover:bg-muted transition-colors`}
                      style={{ padding: '7px 10px 7px 12px' }}
                    >
                      <CatIcon className={`h-3.5 w-3.5 shrink-0 ${color.text} opacity-60`} />
                      <span className="capitalize flex-1 truncate">{v.category}</span>
                      <span className="text-3xs tabular-nums shrink-0 opacity-80">
                        {v.values.length}
                      </span>
                    </button>
                  )
                })}
              </>
            ) : (
              <>
                <div className="px-3 pt-1.5 pb-1.5 border-b border-border/50 flex items-center gap-2">
                  <button
                    onClick={() => setSelectedCategory(null)}
                    className="text-muted-foreground hover:text-foreground transition-colors shrink-0"
                  >
                    <ChevronLeft className="h-3.5 w-3.5" />
                  </button>
                  {SelectedIcon && (
                    <SelectedIcon className={`h-3.5 w-3.5 shrink-0 ${selectedColor!.text}`} />
                  )}
                  <span
                    className={`text-xs font-medium capitalize truncate ${selectedColor!.text}`}
                  >
                    {selectedCategory}
                  </span>
                  <span className="ml-auto text-3xs text-muted-foreground shrink-0">
                    {availableValues.length}
                  </span>
                </div>
                <div className="py-1">
                  {availableValues.length === 0 ? (
                    <div className="px-3 py-3 text-xs text-muted-foreground italic text-center">
                      All values applied
                    </div>
                  ) : (
                    availableValues.map((value, i) => (
                      <button
                        key={value}
                        onClick={() => handleAdd(selectedCategory, value)}
                        className={`flex w-full items-center px-3 py-1.5 text-xs ${selectedColor!.text} hover:bg-primary/10 hover:text-primary transition-colors text-left capitalize ${i < availableValues.length - 1 ? 'border-b border-border/40' : ''}`}
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
