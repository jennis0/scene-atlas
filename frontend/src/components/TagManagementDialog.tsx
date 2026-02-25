import { useState, useCallback, useRef, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Plus,
  Trash2,
  Pencil,
  Check,
  X,
  AlertTriangle,
  Tag,
  Loader2,
  RefreshCw,
} from 'lucide-react'
import { Dialog, DialogContent } from '@/components/ui/dialog'
import { tagApi, searchApi } from '@/lib/api'
import { useJobPolling } from '@/hooks/useJobPolling'
import { COLOR_PALETTE, PALETTE_KEYS, getTagColor } from '@/components/import/tagColors'
import { CATEGORY_ICON_MAP, CATEGORY_ICON_NAMES, getCategoryIcon } from '@/lib/categoryIcons'
import type { TagCategory } from '@/types'

// ── Constants ─────────────────────────────────────────────────────────────────

const DARK_SURFACE = 'hsl(222 22% 10%)'

// ── Helpers ──────────────────────────────────────────────────────────────────

interface TagValueEntry {
  value: string
  aliases: string[]
}

function parseCommonValues(raw: string | null): TagValueEntry[] {
  if (!raw) return []
  try {
    const arr = JSON.parse(raw) as (string | { value: string; aliases?: string[] })[]
    return arr.map((v) =>
      typeof v === 'string'
        ? { value: v, aliases: [] }
        : { value: v.value, aliases: v.aliases ?? [] },
    )
  } catch {
    return []
  }
}

// ── Types ────────────────────────────────────────────────────────────────────

interface TagManagementDialogProps {
  open: boolean
  onClose: () => void
}

type ConfirmAction = {
  label: string
  detail: string
  onConfirm: () => void
  confirmLabel?: string
  confirmStyle?: 'danger' | 'warning'
}

// ── Component ────────────────────────────────────────────────────────────────

export function TagManagementDialog({ open, onClose }: TagManagementDialogProps) {
  const queryClient = useQueryClient()
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null)
  const [confirmAction, setConfirmAction] = useState<ConfirmAction | null>(null)
  const [vocabDirty, setVocabDirty] = useState(false)

  const retagJob = useJobPolling()

  const retagMut = useMutation({
    mutationFn: tagApi.retagAll,
    onSuccess: (data) => {
      setVocabDirty(false)
      retagJob.track(data.job_id)
    },
  })

  const { data: categories = [], isLoading } = useQuery({
    queryKey: ['tagCategories'],
    queryFn: tagApi.getCategories,
    staleTime: 30_000,
    enabled: open,
  })

  const { data: facets } = useQuery({
    queryKey: ['searchFacets'],
    queryFn: searchApi.facets,
    staleTime: 60_000,
    enabled: open,
  })

  const invalidate = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ['tagCategories'] })
    queryClient.invalidateQueries({ queryKey: ['searchFacets'] })
  }, [queryClient])

  useEffect(() => {
    if (retagJob.isComplete) {
      invalidate()
    }
  }, [retagJob.isComplete, invalidate])

  const invalidateAndMark = useCallback(() => {
    setVocabDirty(true)
    invalidate()
  }, [invalidate])

  const activeCat = categories.find((c) => c.name === selectedCategory) ?? null
  const effectiveSelection = activeCat ? activeCat.name : (categories[0]?.name ?? null)

  useEffect(() => {
    if (!selectedCategory && categories.length > 0) {
      setSelectedCategory(categories[0].name)
    }
  }, [categories, selectedCategory])

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-w-3xl w-full h-[75vh] flex flex-col gap-0 border-border/50 bg-card p-0 overflow-hidden">
        {/* Header */}
        <div
          className="px-4 py-3 border-b border-border/60 flex-shrink-0"
          style={{ background: DARK_SURFACE }}
        >
          <div className="flex items-end justify-between">
            <div>
              <div className="flex items-center gap-3">
                <span className="font-display text-[13px] font-medium tracking-[0.06em] text-foreground">
                  Tag Management
                </span>
                <button
                  onClick={() =>
                    setConfirmAction({
                      label: 'Regenerate auto-tags?',
                      detail:
                        'This will delete all automatically assigned tags across every image and regenerate them from filenames. Manually applied tags are kept.',
                      confirmLabel: 'Regenerate',
                      confirmStyle: 'warning',
                      onConfirm: () => {
                        retagMut.mutate()
                        setConfirmAction(null)
                      },
                    })
                  }
                  disabled={retagMut.isPending || retagJob.isRunning}
                  className={`flex items-center gap-1.5 rounded-md px-2 py-1 text-[11px] transition-colors disabled:opacity-40 ${
                    vocabDirty
                      ? 'text-amber-400 bg-amber-400/10 hover:bg-amber-400/20 ring-1 ring-amber-400/30'
                      : 'text-muted-foreground hover:text-amber-400 hover:bg-secondary'
                  }`}
                  title="Regenerate auto-tags for all images from their filenames. Manually applied tags are always preserved."
                >
                  <RefreshCw
                    className={`w-3 h-3 ${retagMut.isPending || retagJob.isRunning ? 'animate-spin' : ''}`}
                    strokeWidth={1.5}
                  />
                  {retagJob.isRunning
                    ? `Retagging${retagJob.progressPct != null ? ` (${retagJob.progressPct}%)` : '…'}`
                    : 'Regenerate auto-tags'}
                </button>
              </div>
              <div className="mt-[3px] h-px w-7 bg-gradient-to-r from-primary to-transparent" />
            </div>
            <button
              onClick={onClose}
              className="rounded-sm p-1 opacity-70 transition-opacity hover:opacity-100 text-muted-foreground hover:text-foreground"
            >
              <X className="h-4 w-4" strokeWidth={1.5} />
              <span className="sr-only">Close</span>
            </button>
          </div>
        </div>

        {isLoading ? (
          <div className="flex-1 flex items-center justify-center">
            <Loader2 className="w-6 h-6 animate-spin text-muted-foreground" />
          </div>
        ) : (
          <div className="flex flex-1 min-h-0">
            {/* Left Panel — Category List */}
            <CategoryList
              categories={categories}
              selected={effectiveSelection}
              onSelect={setSelectedCategory}
              invalidate={invalidateAndMark}
            />

            {/* Right Panel — Category Editor */}
            <div className="flex-1 min-w-0 flex flex-col">
              {effectiveSelection ? (
                <CategoryEditor
                  key={effectiveSelection}
                  category={categories.find((c) => c.name === effectiveSelection)!}
                  invalidate={invalidateAndMark}
                  setConfirmAction={setConfirmAction}
                  onCategoryRenamed={setSelectedCategory}
                  onDeleted={() => {
                    const next = categories.find((c) => c.name !== effectiveSelection)
                    setSelectedCategory(next?.name ?? null)
                  }}
                  facetCounts={facets?.tags[effectiveSelection] ?? []}
                />
              ) : (
                <div className="flex-1 flex items-center justify-center text-muted-foreground text-sm">
                  Create a category to get started
                </div>
              )}
            </div>
          </div>
        )}

        {/* Footer */}
        <div
          className="px-4 py-2.5 border-t border-border/60 flex-shrink-0"
          style={{ background: DARK_SURFACE }}
        >
          <span className="text-[10.5px] text-muted-foreground italic">
            Changes save automatically
          </span>
        </div>

        {/* Confirm overlay */}
        {confirmAction && (
          <ConfirmOverlay action={confirmAction} onCancel={() => setConfirmAction(null)} />
        )}
      </DialogContent>
    </Dialog>
  )
}

// ── Category List (Left Panel) ───────────────────────────────────────────────

function CategoryList({
  categories,
  selected,
  onSelect,
  invalidate,
}: {
  categories: TagCategory[]
  selected: string | null
  onSelect: (name: string) => void
  invalidate: () => void
}) {
  const [creating, setCreating] = useState(false)
  const [newName, setNewName] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)

  const createMut = useMutation({
    mutationFn: (name: string) => tagApi.createCategory({ name }),
    onSuccess: (cat) => {
      invalidate()
      onSelect(cat.name)
      setCreating(false)
      setNewName('')
    },
  })

  useEffect(() => {
    if (creating) inputRef.current?.focus()
  }, [creating])

  const handleCreate = () => {
    const trimmed = newName.trim()
    if (!trimmed) return
    createMut.mutate(trimmed)
  }

  return (
    <div
      className="w-52 shrink-0 border-r border-border/60 flex flex-col overflow-hidden"
      style={{ background: DARK_SURFACE }}
    >
      <div className="flex-1 overflow-y-auto py-[6px]">
        {categories.map((cat) => {
          const colors = getTagColor(cat.color)
          const CatIcon = getCategoryIcon(cat.icon)
          const isActive = cat.name === selected
          const activeClass = `${colors.bg} ${colors.text} font-medium ${colors.border}`

          return (
            <button
              key={cat.name}
              onClick={() => onSelect(cat.name)}
              style={{ padding: '7px 10px 7px 12px' }}
              className={`w-full flex items-center gap-[7px] text-left text-[12px] transition-colors border-l-2 capitalize ${
                isActive ? activeClass : 'text-muted-foreground border-transparent'
              }`}
              onMouseEnter={(e) => {
                if (!isActive)
                  (e.currentTarget as HTMLElement).style.background = 'hsl(222 20% 14%)'
              }}
              onMouseLeave={(e) => {
                if (!isActive) (e.currentTarget as HTMLElement).style.background = ''
              }}
            >
              <CatIcon
                className={`h-3 w-3 flex-shrink-0 ${isActive ? '' : `${colors.text} opacity-60`}`}
                strokeWidth={1.5}
              />
              <span className="truncate flex-1">{cat.name}</span>
            </button>
          )
        })}

        {/* Inline create */}
        {creating ? (
          <div className="flex items-center gap-1 px-2 py-1.5 mx-1">
            <input
              ref={inputRef}
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') handleCreate()
                if (e.key === 'Escape') {
                  setCreating(false)
                  setNewName('')
                }
              }}
              placeholder="name"
              className="flex-1 min-w-0 bg-secondary border border-border rounded px-1.5 py-0.5 text-[12px] text-foreground placeholder-muted-foreground focus:outline-none focus:border-primary/50"
            />
            <button onClick={handleCreate} className="p-0.5 text-primary hover:text-primary/80">
              <Check className="w-3 h-3" strokeWidth={1.5} />
            </button>
            <button
              onClick={() => {
                setCreating(false)
                setNewName('')
              }}
              className="p-0.5 text-muted-foreground hover:text-foreground"
            >
              <X className="w-3 h-3" strokeWidth={1.5} />
            </button>
          </div>
        ) : (
          <button
            onClick={() => setCreating(true)}
            style={{ padding: '7px 10px 7px 12px' }}
            className="w-full flex items-center gap-[7px] text-[12px] text-muted-foreground hover:text-primary/80 transition-colors border-l-2 border-transparent"
            onMouseEnter={(e) => {
              ;(e.currentTarget as HTMLElement).style.background = 'hsl(222 20% 14%)'
            }}
            onMouseLeave={(e) => {
              ;(e.currentTarget as HTMLElement).style.background = ''
            }}
          >
            <Plus className="h-3 w-3 shrink-0" strokeWidth={1.5} />
            <span>New category</span>
          </button>
        )}
      </div>
    </div>
  )
}

// ── Category Editor (Right Panel) ────────────────────────────────────────────

function CategoryEditor({
  category,
  invalidate,
  setConfirmAction,
  onCategoryRenamed,
  onDeleted,
  facetCounts,
}: {
  category: TagCategory
  invalidate: () => void
  setConfirmAction: (a: ConfirmAction | null) => void
  onCategoryRenamed: (name: string) => void
  onDeleted: () => void
  facetCounts: { value: string; count: number }[]
}) {
  const [editingName, setEditingName] = useState(false)
  const [nameInput, setNameInput] = useState(category.name)
  const [description, setDescription] = useState(category.description ?? '')
  const nameRef = useRef<HTMLInputElement>(null)

  const colors = getTagColor(category.color)
  const CatIcon = getCategoryIcon(category.icon)

  const values = parseCommonValues(category.common_values)

  const updateMut = useMutation({
    mutationFn: (payload: Parameters<typeof tagApi.updateCategory>[1]) =>
      tagApi.updateCategory(category.name, payload),
    onSuccess: (res) => {
      invalidate()
      if (res.category.name !== category.name) {
        onCategoryRenamed(res.category.name)
      }
    },
  })

  const deleteMut = useMutation({
    mutationFn: () => tagApi.deleteCategory(category.name),
    onSuccess: () => {
      invalidate()
      onDeleted()
    },
  })

  const handleNameSave = () => {
    const trimmed = nameInput.trim()
    if (!trimmed || trimmed === category.name) {
      setEditingName(false)
      setNameInput(category.name)
      return
    }
    updateMut.mutate({ name: trimmed })
    setEditingName(false)
  }

  const handleDescSave = () => {
    if (description.trim() !== (category.description ?? '')) {
      updateMut.mutate({ description: description.trim() || undefined })
    }
  }

  const handleDeleteClick = () => {
    setConfirmAction({
      label: `Delete "${category.name}"?`,
      detail: 'This will permanently remove the category and delete all its tags from every image.',
      onConfirm: () => {
        deleteMut.mutate()
        setConfirmAction(null)
      },
    })
  }

  useEffect(() => {
    if (editingName) nameRef.current?.focus()
  }, [editingName])

  return (
    <div className="flex flex-col h-full">
      {/* Heading area */}
      <div className="px-4 pt-3.5 pb-3 border-b border-border/50 flex-shrink-0">
        <p className="text-[9.5px] font-medium tracking-[0.18em] uppercase text-muted-foreground mb-1.5">
          Editing
        </p>
        <div className="flex items-center gap-2">
          <CatIcon
            className={`h-3.5 w-3.5 flex-shrink-0 opacity-80 ${colors.text}`}
            strokeWidth={1.5}
          />
          {editingName ? (
            <>
              <input
                ref={nameRef}
                value={nameInput}
                onChange={(e) => setNameInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') handleNameSave()
                  if (e.key === 'Escape') {
                    setEditingName(false)
                    setNameInput(category.name)
                  }
                }}
                className="flex-1 bg-secondary border border-border rounded px-2 py-1 font-display text-[15px] text-foreground focus:outline-none focus:border-primary/50"
              />
              <button onClick={handleNameSave} className="p-0.5 text-primary hover:text-primary/80">
                <Check className="w-3.5 h-3.5" strokeWidth={1.5} />
              </button>
              <button
                onClick={() => {
                  setEditingName(false)
                  setNameInput(category.name)
                }}
                className="p-0.5 text-muted-foreground hover:text-foreground"
              >
                <X className="w-3.5 h-3.5" strokeWidth={1.5} />
              </button>
            </>
          ) : (
            <>
              <button
                onClick={() => setEditingName(true)}
                className="flex items-center gap-1.5 group"
                title="Click to rename"
              >
                <h3
                  className={`font-display text-[17px] font-medium tracking-[0.04em] leading-none capitalize ${colors.text}`}
                >
                  {category.name}
                </h3>
                <Pencil
                  className="w-3 h-3 text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity"
                  strokeWidth={1.5}
                />
              </button>
              <span className="flex-1" />
              <button
                onClick={handleDeleteClick}
                className="p-1 text-muted-foreground hover:text-destructive/70 transition-colors rounded"
                title={`Delete ${category.name}`}
              >
                <Trash2 className="w-3 h-3" strokeWidth={1.5} />
              </button>
            </>
          )}
        </div>
        <input
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          onBlur={handleDescSave}
          onKeyDown={(e) => {
            if (e.key === 'Enter') handleDescSave()
          }}
          placeholder="Add a description…"
          className="mt-1.5 w-full bg-transparent border-none text-[12px] text-muted-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:text-foreground"
        />
      </div>

      {/* Icon picker */}
      <div className="px-4 py-2.5 border-b border-border/60">
        <div className="text-[10px] text-muted-foreground uppercase tracking-[0.12em] mb-2">
          Icon
        </div>
        <div className="grid grid-cols-8 gap-1">
          {CATEGORY_ICON_NAMES.map((iconName) => {
            const IconComp = CATEGORY_ICON_MAP[iconName]
            const isSelected = category.icon === iconName
            return (
              <button
                key={iconName}
                onClick={() => updateMut.mutate({ icon: iconName })}
                title={iconName}
                className={`flex items-center justify-center p-1.5 rounded-md transition-all ${
                  isSelected
                    ? `${colors.bg} ${colors.text} ring-1 ${colors.border}`
                    : 'text-muted-foreground hover:text-foreground hover:bg-secondary'
                }`}
              >
                <IconComp className="h-3 w-3" strokeWidth={1.5} />
              </button>
            )
          })}
        </div>
      </div>

      {/* Colour picker */}
      <div className="px-4 py-2.5 border-b border-border/60">
        <div className="text-[10px] text-muted-foreground uppercase tracking-[0.12em] mb-2">
          Color
        </div>
        <div className="grid grid-cols-12 gap-1.5">
          {PALETTE_KEYS.map((key) => {
            const isSelected = category.color === key
            return (
              <button
                key={key}
                onClick={() => updateMut.mutate({ color: key })}
                className={`w-full aspect-square rounded-full transition-all ${COLOR_PALETTE[key].dot} ${
                  isSelected
                    ? 'scale-105 outline outline-2 outline-offset-2 outline-white/60'
                    : 'opacity-60 hover:opacity-100 hover:scale-105'
                }`}
                title={key}
              />
            )
          })}
        </div>
      </div>

      {/* Tag Values */}
      <div className="flex-1 overflow-y-auto">
        <TagValueList
          categoryName={category.name}
          values={values}
          facetCounts={facetCounts}
          invalidate={invalidate}
          setConfirmAction={setConfirmAction}
        />
      </div>
    </div>
  )
}

// ── Tag Value List ───────────────────────────────────────────────────────────

function TagValueList({
  categoryName,
  values,
  facetCounts,
  invalidate,
  setConfirmAction,
}: {
  categoryName: string
  values: TagValueEntry[]
  facetCounts: { value: string; count: number }[]
  invalidate: () => void
  setConfirmAction: (a: ConfirmAction | null) => void
}) {
  const [addingValue, setAddingValue] = useState(false)
  const [newValue, setNewValue] = useState('')
  const addRef = useRef<HTMLInputElement>(null)

  const upsertMut = useMutation({
    mutationFn: ({ value, aliases }: { value: string; aliases?: string[] }) =>
      tagApi.upsertTagValue(categoryName, value, aliases),
    onSuccess: () => invalidate(),
  })

  const deleteMut = useMutation({
    mutationFn: (value: string) => tagApi.deleteTagValue(categoryName, value),
    onSuccess: () => {
      invalidate()
      setConfirmAction(null)
    },
  })

  useEffect(() => {
    if (addingValue) addRef.current?.focus()
  }, [addingValue])

  const handleAdd = () => {
    const trimmed = newValue.trim()
    if (!trimmed) return
    upsertMut.mutate({ value: trimmed })
    setNewValue('')
  }

  return (
    <div>
      {values.map((entry) => {
        const count = facetCounts.find((f) => f.value === entry.value)?.count ?? 0
        return (
          <TagValueRow
            key={entry.value}
            categoryName={categoryName}
            entry={entry}
            count={count}
            invalidate={invalidate}
            onDelete={() => {
              if (count > 0) {
                setConfirmAction({
                  label: `Delete "${entry.value}"?`,
                  detail: `This will remove the tag from ${count} image${count !== 1 ? 's' : ''} and delete it from the vocabulary.`,
                  onConfirm: () => deleteMut.mutate(entry.value),
                })
              } else {
                deleteMut.mutate(entry.value)
              }
            }}
          />
        )
      })}

      {/* Add new value */}
      {addingValue ? (
        <div className="flex items-center gap-1.5 px-4 py-2">
          <input
            ref={addRef}
            value={newValue}
            onChange={(e) => setNewValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') handleAdd()
              if (e.key === 'Escape') {
                setAddingValue(false)
                setNewValue('')
              }
            }}
            placeholder="tag value"
            className="flex-1 min-w-0 bg-secondary border border-border rounded px-2 py-1 text-[13px] text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:border-primary/50"
          />
          <button onClick={handleAdd} className="p-1 text-primary hover:text-primary/80">
            <Check className="w-3.5 h-3.5" strokeWidth={1.5} />
          </button>
          <button
            onClick={() => {
              setAddingValue(false)
              setNewValue('')
            }}
            className="p-1 text-muted-foreground hover:text-foreground"
          >
            <X className="w-3.5 h-3.5" strokeWidth={1.5} />
          </button>
        </div>
      ) : (
        <button
          onClick={() => setAddingValue(true)}
          className="flex items-center gap-1.5 px-4 py-2 text-[12px] text-muted-foreground hover:text-primary/80 transition-colors"
        >
          <Plus className="w-3 h-3" strokeWidth={1.5} />
          <span>Add value</span>
        </button>
      )}
    </div>
  )
}

// ── Single Tag Value Row ─────────────────────────────────────────────────────

function TagValueRow({
  categoryName,
  entry,
  count,
  invalidate,
  onDelete,
}: {
  categoryName: string
  entry: TagValueEntry
  count: number
  invalidate: () => void
  onDelete: () => void
}) {
  const [editingValue, setEditingValue] = useState(false)
  const [editVal, setEditVal] = useState(entry.value)
  const [editingAliases, setEditingAliases] = useState(false)
  const [aliasInput, setAliasInput] = useState('')
  const editRef = useRef<HTMLInputElement>(null)
  const aliasRef = useRef<HTMLInputElement>(null)

  const renameMut = useMutation({
    mutationFn: (newValue: string) => tagApi.renameTagValue(categoryName, entry.value, newValue),
    onSuccess: () => {
      invalidate()
      setEditingValue(false)
    },
  })

  const upsertMut = useMutation({
    mutationFn: (aliases: string[]) => tagApi.upsertTagValue(categoryName, entry.value, aliases),
    onSuccess: () => invalidate(),
  })

  useEffect(() => {
    if (editingValue) editRef.current?.focus()
  }, [editingValue])

  useEffect(() => {
    if (editingAliases) aliasRef.current?.focus()
  }, [editingAliases])

  const handleRename = () => {
    const trimmed = editVal.trim()
    if (!trimmed || trimmed === entry.value) {
      setEditingValue(false)
      setEditVal(entry.value)
      return
    }
    renameMut.mutate(trimmed)
  }

  const addAlias = () => {
    const trimmed = aliasInput.trim()
    if (!trimmed || entry.aliases.includes(trimmed)) return
    upsertMut.mutate([...entry.aliases, trimmed])
    setAliasInput('')
  }

  const removeAlias = (alias: string) => {
    upsertMut.mutate(entry.aliases.filter((a) => a !== alias))
  }

  return (
    <div className="group px-4 py-2 hover:bg-secondary/30 transition-colors">
      {/* Main row */}
      <div className="flex items-center gap-2">
        {editingValue ? (
          <>
            <input
              ref={editRef}
              value={editVal}
              onChange={(e) => setEditVal(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') handleRename()
                if (e.key === 'Escape') {
                  setEditingValue(false)
                  setEditVal(entry.value)
                }
              }}
              className="flex-1 min-w-0 bg-secondary border border-border rounded px-2 py-0.5 text-[13px] text-foreground focus:outline-none focus:border-primary/50"
            />
            <button onClick={handleRename} className="p-0.5 text-primary hover:text-primary/80">
              <Check className="w-3 h-3" strokeWidth={1.5} />
            </button>
            <button
              onClick={() => {
                setEditingValue(false)
                setEditVal(entry.value)
              }}
              className="p-0.5 text-muted-foreground hover:text-foreground"
            >
              <X className="w-3 h-3" strokeWidth={1.5} />
            </button>
          </>
        ) : (
          <>
            <span className="text-[13px] text-foreground capitalize">{entry.value}</span>
            <span className="flex-1" />
            {count > 0 && (
              <span className="text-[12px] text-muted-foreground tabular-nums shrink-0 w-8 text-right">
                {count}
              </span>
            )}
            <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity ml-1">
              <button
                onClick={() => setEditingAliases(!editingAliases)}
                className="p-1 text-muted-foreground hover:text-foreground"
                title="Edit aliases"
              >
                <Tag className="w-3 h-3" strokeWidth={1.5} />
              </button>
              <button
                onClick={() => setEditingValue(true)}
                className="p-1 text-muted-foreground hover:text-foreground"
                title="Rename"
              >
                <Pencil className="w-3 h-3" strokeWidth={1.5} />
              </button>
              <button
                onClick={onDelete}
                className="p-1 text-muted-foreground hover:text-destructive/70"
                title="Delete"
              >
                <Trash2 className="w-3 h-3" strokeWidth={1.5} />
              </button>
            </div>
          </>
        )}
      </div>

      {/* Aliases row */}
      {!editingValue && (
        <div className="mt-0.5 ml-0.5">
          {editingAliases ? (
            <div className="flex flex-wrap items-center gap-1">
              {entry.aliases.map((alias) => (
                <span
                  key={alias}
                  className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[11px] bg-secondary text-muted-foreground capitalize"
                >
                  {alias}
                  <button
                    onClick={() => removeAlias(alias)}
                    className="text-muted-foreground/60 hover:text-destructive/70"
                  >
                    <X className="w-2.5 h-2.5" strokeWidth={1.5} />
                  </button>
                </span>
              ))}
              <input
                ref={aliasRef}
                value={aliasInput}
                onChange={(e) => setAliasInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') addAlias()
                  if (e.key === 'Escape') setEditingAliases(false)
                }}
                placeholder="add alias…"
                className="h-6 px-1.5 text-[11px] bg-secondary/50 border border-border/60 rounded text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:border-primary/40"
              />
              <button
                onClick={() => setEditingAliases(false)}
                className="p-0.5 text-muted-foreground hover:text-foreground"
                title="Done"
              >
                <Check className="w-3 h-3" strokeWidth={1.5} />
              </button>
            </div>
          ) : (
            entry.aliases.length > 0 && (
              <p className="text-[11px] text-muted-foreground capitalize leading-tight">
                {entry.aliases.join(', ')}
              </p>
            )
          )}
        </div>
      )}
    </div>
  )
}

// ── Confirm Overlay ──────────────────────────────────────────────────────────

function ConfirmOverlay({ action, onCancel }: { action: ConfirmAction; onCancel: () => void }) {
  return (
    <div className="absolute inset-0 z-10 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="bg-card border border-border rounded-lg p-5 max-w-sm mx-4 shadow-xl">
        <div className="flex items-start gap-3">
          <AlertTriangle className="w-4 h-4 text-primary shrink-0 mt-0.5" strokeWidth={1.5} />
          <div>
            <h4 className="text-sm font-semibold text-foreground">{action.label}</h4>
            <p className="text-[12px] text-muted-foreground mt-1">{action.detail}</p>
          </div>
        </div>
        <div className="flex justify-end gap-2 mt-4">
          <button
            onClick={onCancel}
            className="px-3 py-1.5 text-[12px] text-muted-foreground hover:text-foreground rounded-md hover:bg-secondary transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={action.onConfirm}
            className={`px-3 py-1.5 text-[12px] rounded-md border transition-colors ${
              action.confirmStyle === 'warning'
                ? 'text-primary hover:text-primary/80 bg-primary/10 hover:bg-primary/20 border-primary/20'
                : 'text-destructive hover:text-destructive/80 bg-destructive/10 hover:bg-destructive/20 border-destructive/20'
            }`}
          >
            {action.confirmLabel ?? 'Delete'}
          </button>
        </div>
      </div>
    </div>
  )
}
