import { useState, useCallback, useRef, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Plus,
  Trash2,
  Pencil,
  Check,
  X,
  AlertTriangle,
  GripVertical,
  Tag,
  Loader2,
} from 'lucide-react'
import { Dialog, DialogContent } from '@/components/ui/dialog'
import { tagApi, searchApi } from '@/lib/api'
import { COLOR_PALETTE, PALETTE_KEYS, getTagColor } from '@/components/import/tagColors'
import type { TagCategory } from '@/types'

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
      typeof v === 'string' ? { value: v, aliases: [] } : { value: v.value, aliases: v.aliases ?? [] },
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
}

// ── Component ────────────────────────────────────────────────────────────────

export function TagManagementDialog({ open, onClose }: TagManagementDialogProps) {
  const queryClient = useQueryClient()
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null)
  const [confirmAction, setConfirmAction] = useState<ConfirmAction | null>(null)

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

  // Auto-select first category
  const activeCat = categories.find((c) => c.name === selectedCategory) ?? null
  const effectiveSelection = activeCat ? activeCat.name : categories[0]?.name ?? null

  // Sync selection when categories change
  useEffect(() => {
    if (!selectedCategory && categories.length > 0) {
      setSelectedCategory(categories[0].name)
    }
  }, [categories, selectedCategory])

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent
        className="max-w-3xl w-full h-[75vh] flex flex-col gap-0 border-zinc-700/50 bg-zinc-900 p-0 overflow-hidden"
        onClose={onClose}
      >
        {/* Header */}
        <div className="flex items-center gap-2 px-3 py-2 border-b border-zinc-800">
          <Tag className="w-3.5 h-3.5 text-amber-400" />
          <h2 className="text-xs font-semibold text-zinc-300 tracking-wide uppercase">Tag Management</h2>
        </div>

        {isLoading ? (
          <div className="flex-1 flex items-center justify-center">
            <Loader2 className="w-6 h-6 animate-spin text-zinc-500" />
          </div>
        ) : (
          <div className="flex flex-1 min-h-0">
            {/* Left Panel — Category List */}
            <CategoryList
              categories={categories}
              selected={effectiveSelection}
              onSelect={setSelectedCategory}
              invalidate={invalidate}
              setConfirmAction={setConfirmAction}
            />

            {/* Right Panel — Category Editor */}
            <div className="flex-1 min-w-0 flex flex-col">
              {effectiveSelection ? (
                <CategoryEditor
                  key={effectiveSelection}
                  category={categories.find((c) => c.name === effectiveSelection)!}
                  invalidate={invalidate}
                  setConfirmAction={setConfirmAction}
                  onCategoryRenamed={setSelectedCategory}
                  facetCounts={facets?.tags[effectiveSelection] ?? []}
                />
              ) : (
                <div className="flex-1 flex items-center justify-center h-full text-zinc-500 text-sm">
                  Create a category to get started
                </div>
              )}
            </div>
          </div>
        )}

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
  setConfirmAction,
}: {
  categories: TagCategory[]
  selected: string | null
  onSelect: (name: string) => void
  invalidate: () => void
  setConfirmAction: (a: ConfirmAction | null) => void
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

  const deleteMut = useMutation({
    mutationFn: (name: string) => tagApi.deleteCategory(name),
    onSuccess: () => {
      invalidate()
      onSelect(categories.find((c) => c.name !== selected)?.name ?? '')
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
    <div className="w-52 shrink-0 border-r border-zinc-800 flex flex-col">
      <div className="flex-1 overflow-y-auto">
        {categories.map((cat) => {
          const color = getTagColor(cat.color)
          const isActive = cat.name === selected
          return (
            <button
              key={cat.name}
              onClick={() => onSelect(cat.name)}
              className={`w-full flex items-center gap-2.5 px-4 py-2 text-left text-base capitalize transition-colors group ${
                isActive
                  ? 'bg-zinc-800 text-zinc-100'
                  : 'text-zinc-400 hover:bg-zinc-800/50 hover:text-zinc-200'
              }`}
            >
              <span className={`w-2 h-2 rounded-full shrink-0 ${color.dot}`} />
              <span className="truncate flex-1">{cat.name}</span>
              <button
                onClick={(e) => {
                  e.stopPropagation()
                  setConfirmAction({
                    label: `Delete "${cat.name}"?`,
                    detail: 'This will permanently remove the category and delete all its tags from every image.',
                    onConfirm: () => {
                      deleteMut.mutate(cat.name)
                      setConfirmAction(null)
                    },
                  })
                }}
                className="opacity-0 group-hover:opacity-100 p-0.5 text-zinc-500 hover:text-red-400 transition-all"
              >
                <Trash2 className="w-3 h-3" />
              </button>
            </button>
          )
        })}

        {/* Inline create */}
        {creating ? (
          <div className="px-2 py-1 flex items-center gap-1">
            <input
              ref={inputRef}
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') handleCreate()
                if (e.key === 'Escape') { setCreating(false); setNewName('') }
              }}
              placeholder="name"
              className="flex-1 min-w-0 bg-zinc-800 border border-zinc-700 rounded px-1.5 py-0.5 text-xs text-zinc-100 placeholder-zinc-500 focus:outline-none focus:border-amber-500/50"
            />
            <button onClick={handleCreate} className="p-0.5 text-amber-400 hover:text-amber-300">
              <Check className="w-3 h-3" />
            </button>
            <button onClick={() => { setCreating(false); setNewName('') }} className="p-0.5 text-zinc-500 hover:text-zinc-300">
              <X className="w-3 h-3" />
            </button>
          </div>
        ) : (
          <button
            onClick={() => setCreating(true)}
            className="w-full flex items-center gap-2 px-4 py-2 text-base text-zinc-500 hover:text-amber-400 transition-colors"
          >
            <Plus className="w-3 h-3" />
            <span>Add category</span>
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
  facetCounts,
}: {
  category: TagCategory
  invalidate: () => void
  setConfirmAction: (a: ConfirmAction | null) => void
  onCategoryRenamed: (name: string) => void
  facetCounts: { value: string; count: number }[]
}) {
  const [editingName, setEditingName] = useState(false)
  const [nameInput, setNameInput] = useState(category.name)
  const [description, setDescription] = useState(category.description ?? '')
  const nameRef = useRef<HTMLInputElement>(null)

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

  useEffect(() => {
    if (editingName) nameRef.current?.focus()
  }, [editingName])

  return (
    <div className="flex flex-col h-full">
      {/* Name + description */}
      <div className="px-4 pt-3 pb-2 border-b border-zinc-800/60">
        {editingName ? (
          <div className="flex items-center gap-2">
            <input
              ref={nameRef}
              value={nameInput}
              onChange={(e) => setNameInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') handleNameSave()
                if (e.key === 'Escape') { setEditingName(false); setNameInput(category.name) }
              }}
              className="bg-zinc-800 border border-zinc-700 rounded px-2 py-1 text-sm font-semibold text-zinc-100 focus:outline-none focus:border-amber-500/50"
            />
            <button onClick={handleNameSave} className="p-0.5 text-amber-400 hover:text-amber-300">
              <Check className="w-3.5 h-3.5" />
            </button>
            <button onClick={() => { setEditingName(false); setNameInput(category.name) }} className="p-0.5 text-zinc-500 hover:text-zinc-300">
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        ) : (
          <div className="flex items-center gap-2 group">
            <h3 className="text-base font-semibold text-zinc-100 capitalize">{category.name}</h3>
            <button
              onClick={() => setEditingName(true)}
              className="p-0.5 text-zinc-600 hover:text-zinc-300 opacity-0 group-hover:opacity-100 transition-opacity"
            >
              <Pencil className="w-3.5 h-3.5" />
            </button>
          </div>
        )}
        <input
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          onBlur={handleDescSave}
          onKeyDown={(e) => { if (e.key === 'Enter') handleDescSave() }}
          placeholder="Add a description..."
          className="mt-1 w-full bg-transparent border-none text-sm text-zinc-500 placeholder-zinc-600 focus:outline-none focus:text-zinc-300"
        />
      </div>

      {/* Colour picker — forced 12-per-row grid */}
      <div className="px-4 py-2 border-b border-zinc-800/60">
        <div className="text-xs text-zinc-500 mb-1.5">Color</div>
        <div className="grid grid-cols-12 gap-1.5">
          {PALETTE_KEYS.map((key) => {
            const isSelected = category.color === key
            return (
              <button
                key={key}
                onClick={() => updateMut.mutate({ color: key })}
                className={`w-full aspect-square rounded transition-all ${COLOR_PALETTE[key].dot} ${
                  isSelected
                    ? 'ring-2 ring-white/70 ring-offset-2 ring-offset-zinc-900'
                    : 'opacity-60 hover:opacity-100'
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
    // Keep adding mode open for rapid entry
  }

  return (
    <div className="space-y-1">
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
              if (e.key === 'Escape') { setAddingValue(false); setNewValue('') }
            }}
            placeholder="tag value"
            className="flex-1 min-w-0 bg-zinc-800 border border-zinc-700 rounded px-2 py-1 text-sm text-zinc-100 placeholder-zinc-500 focus:outline-none focus:border-amber-500/50"
          />
          <button onClick={handleAdd} className="p-1 text-amber-400 hover:text-amber-300">
            <Check className="w-4 h-4" />
          </button>
          <button onClick={() => { setAddingValue(false); setNewValue('') }} className="p-1 text-zinc-500 hover:text-zinc-300">
            <X className="w-4 h-4" />
          </button>
        </div>
      ) : (
        <button
          onClick={() => setAddingValue(true)}
          className="flex items-center gap-1.5 px-4 py-2 text-sm text-zinc-500 hover:text-amber-400 transition-colors"
        >
          <Plus className="w-4 h-4" />
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
  const [editing, setEditing] = useState(false)
  const [editValue, setEditValue] = useState(entry.value)
  const [showAliases, setShowAliases] = useState(false)
  const [aliasInput, setAliasInput] = useState('')
  const editRef = useRef<HTMLInputElement>(null)
  const aliasRef = useRef<HTMLInputElement>(null)

  const renameMut = useMutation({
    mutationFn: (newValue: string) => tagApi.renameTagValue(categoryName, entry.value, newValue),
    onSuccess: () => {
      invalidate()
      setEditing(false)
    },
  })

  const upsertMut = useMutation({
    mutationFn: (aliases: string[]) => tagApi.upsertTagValue(categoryName, entry.value, aliases),
    onSuccess: () => invalidate(),
  })

  useEffect(() => {
    if (editing) editRef.current?.focus()
  }, [editing])

  useEffect(() => {
    if (showAliases) aliasRef.current?.focus()
  }, [showAliases])

  const handleRename = () => {
    const trimmed = editValue.trim()
    if (!trimmed || trimmed === entry.value) {
      setEditing(false)
      setEditValue(entry.value)
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
    <div className="group">
      <div className="flex items-center gap-2 px-4 py-1.5 hover:bg-zinc-800/40 transition-colors">
        {editing ? (
          <>
            <input
              ref={editRef}
              value={editValue}
              onChange={(e) => setEditValue(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') handleRename()
                if (e.key === 'Escape') { setEditing(false); setEditValue(entry.value) }
              }}
              className="flex-1 min-w-0 bg-zinc-800 border border-zinc-700 rounded px-2 py-1 text-sm text-zinc-100 focus:outline-none focus:border-amber-500/50"
            />
            <button onClick={handleRename} className="p-0.5 text-amber-400 hover:text-amber-300">
              <Check className="w-3 h-3" />
            </button>
            <button onClick={() => { setEditing(false); setEditValue(entry.value) }} className="p-0.5 text-zinc-500 hover:text-zinc-300">
              <X className="w-3 h-3" />
            </button>
          </>
        ) : (
          <>
            <span className="text-base text-zinc-300 shrink-0 capitalize">{entry.value}</span>
            {entry.aliases.length > 0 && (
              <span className="text-sm text-zinc-600 truncate capitalize">
                · {entry.aliases.join(', ')}
              </span>
            )}
            <span className="flex-1" />
            <span className="text-sm text-zinc-600 shrink-0 tabular-nums w-8 text-right">
              {count}
            </span>
            <div className="flex items-center gap-1 opacity-20 group-hover:opacity-100 transition-opacity ml-2">
              <button onClick={() => setShowAliases(!showAliases)} className="p-1 text-zinc-400 hover:text-zinc-100" title="Edit aliases">
                <GripVertical className="w-4 h-4" />
              </button>
              <button onClick={() => setEditing(true)} className="p-1 text-zinc-400 hover:text-zinc-100" title="Rename">
                <Pencil className="w-4 h-4" />
              </button>
              <button onClick={onDelete} className="p-1 text-zinc-400 hover:text-red-400" title="Delete">
                <Trash2 className="w-4 h-4" />
              </button>
            </div>
          </>
        )}
      </div>

      {showAliases && (
        <div className="px-3 pb-1 ml-3 border-l border-zinc-700/40">
          <div className="flex flex-wrap gap-1 pt-0.5">
            {entry.aliases.map((alias) => (
              <span key={alias} className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-xs bg-zinc-800 text-zinc-400 border border-zinc-700/40 capitalize">
                {alias}
                <button onClick={() => removeAlias(alias)} className="text-zinc-600 hover:text-red-400">
                  <X className="w-2.5 h-2.5" />
                </button>
              </span>
            ))}
          </div>
          <div className="flex items-center gap-1 mt-1">
            <input
              ref={aliasRef}
              value={aliasInput}
              onChange={(e) => setAliasInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') addAlias()
                if (e.key === 'Escape') setShowAliases(false)
              }}
              placeholder="add alias..."
              className="flex-1 min-w-0 bg-zinc-800/50 border border-zinc-700/40 rounded px-1.5 py-0.5 text-xs text-zinc-300 placeholder-zinc-600 focus:outline-none focus:border-amber-500/50"
            />
            <button onClick={addAlias} className="p-0.5 text-amber-400 hover:text-amber-300">
              <Check className="w-3 h-3" />
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

// ── Confirm Overlay ──────────────────────────────────────────────────────────

function ConfirmOverlay({
  action,
  onCancel,
}: {
  action: ConfirmAction
  onCancel: () => void
}) {
  return (
    <div className="absolute inset-0 z-10 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="bg-zinc-900 border border-zinc-700 rounded-lg p-5 max-w-sm mx-4 shadow-xl">
        <div className="flex items-start gap-3">
          <AlertTriangle className="w-5 h-5 text-amber-400 shrink-0 mt-0.5" />
          <div>
            <h4 className="text-sm font-semibold text-zinc-100">{action.label}</h4>
            <p className="text-xs text-zinc-400 mt-1">{action.detail}</p>
          </div>
        </div>
        <div className="flex justify-end gap-2 mt-4">
          <button
            onClick={onCancel}
            className="px-3 py-1.5 text-sm text-zinc-400 hover:text-zinc-200 rounded-md hover:bg-zinc-800 transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={action.onConfirm}
            className="px-3 py-1.5 text-sm text-red-400 hover:text-red-300 bg-red-400/10 hover:bg-red-400/20 rounded-md border border-red-400/20 transition-colors"
          >
            Delete
          </button>
        </div>
      </div>
    </div>
  )
}
