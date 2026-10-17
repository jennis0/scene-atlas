import { useState, useCallback, useRef, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus, Trash2, Check, X, Loader2, RefreshCw, Pencil } from 'lucide-react'
import { Dialog, DialogContent } from '@/components/ui/dialog'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { tagApi, searchApi } from '@/lib/api'
import { QUERY_KEYS, invalidateTagQueries } from '@/lib/queryKeys'
import { useJobPolling } from '@/hooks/useJobPolling'
import {
  PALETTE_KEYS,
  getTagColor,
  getDotColor,
  type TagColor,
} from '@/components/import/tagColors'
import { useTheme } from '@/contexts/ThemeContext'
import { CATEGORY_ICON_MAP, CATEGORY_ICON_NAMES, getCategoryIcon } from '@/lib/categoryIcons'
import { onInlineEditKey } from '@/lib/inlineEditKeys'
import { parseCommonValues, type TagValueEntry } from '@/components/import/types'
import type { TagCategory } from '@/types'
import { PanelTitle } from '@/components/ui/panel-title'

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
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.backgroundJobs })
    },
  })

  const { data: categories = [], isLoading } = useQuery({
    queryKey: QUERY_KEYS.tagCategories,
    queryFn: tagApi.getCategories,
    staleTime: 30_000,
    enabled: open,
  })

  const { data: facets } = useQuery({
    queryKey: QUERY_KEYS.searchFacets,
    queryFn: searchApi.facets,
    staleTime: 60_000,
    enabled: open,
  })

  const invalidate = useCallback(() => {
    invalidateTagQueries(queryClient)
  }, [queryClient])

  useEffect(() => {
    if (retagJob.isComplete) invalidate()
  }, [retagJob.isComplete, invalidate])

  const invalidateAndMark = useCallback(() => {
    setVocabDirty(true)
    invalidate()
  }, [invalidate])

  const effectiveSelection =
    categories.find((c) => c.name === selectedCategory)?.name ?? categories[0]?.name ?? null

  return (
    <>
      <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
        <DialogContent className="max-w-[600px] w-full h-[75vh] flex flex-col gap-0 border-border/50 bg-card p-0 overflow-hidden">
          <div
            className="px-4 border-b border-border flex-shrink-0 bg-popover"
            style={{ padding: '10px 12px 10px 16px' }}
          >
            <div className="flex items-center justify-between">
              <PanelTitle>Tag Management</PanelTitle>
              <button
                onClick={onClose}
                className="h-7 w-7 rounded flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors"
              >
                <X className="h-3.5 w-3.5" />
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
              <CategoryList
                categories={categories}
                selected={effectiveSelection}
                onSelect={setSelectedCategory}
                invalidate={invalidateAndMark}
              />
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

          <div
            className="border-t border-border flex-shrink-0 bg-popover flex items-center justify-between"
            style={{ padding: '8px 16px' }}
          >
            <span className="text-[11px] text-muted-foreground italic">
              Click a value to rename · click aliases to edit
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
              className={`flex items-center gap-[5px] transition-colors disabled:opacity-30 ${
                vocabDirty ? 'text-primary' : 'text-muted-foreground hover:text-foreground'
              }`}
              style={{
                fontSize: '11.5px',
                fontWeight: 500,
                letterSpacing: '0.02em',
                ...(vocabDirty
                  ? {
                      background: 'hsl(var(--primary) / 0.12)',
                      border: '1px solid hsl(var(--primary) / 0.35)',
                      borderRadius: 5,
                      padding: '4px 10px',
                    }
                  : {
                      background: 'transparent',
                      border: '1px solid transparent',
                      borderRadius: 5,
                      padding: '4px 10px',
                    }),
              }}
              title="Regenerate auto-tags for all images from their filenames. Manually applied tags are always preserved."
            >
              <RefreshCw
                className={retagMut.isPending || retagJob.isRunning ? 'animate-spin' : ''}
                style={{ width: 11, height: 11 }}
              />
              {retagJob.isRunning
                ? `Retagging${retagJob.progressPct != null ? ` (${retagJob.progressPct}%)` : '…'}`
                : 'Regenerate auto-tags'}
            </button>
          </div>
        </DialogContent>
      </Dialog>
      <ConfirmDialog
        open={confirmAction !== null}
        onOpenChange={(open) => {
          if (!open) setConfirmAction(null)
        }}
        title={confirmAction?.label ?? ''}
        description={confirmAction?.detail ?? ''}
        confirmLabel={confirmAction?.confirmLabel ?? 'Delete'}
        confirmVariant={confirmAction?.confirmStyle === 'warning' ? 'default' : 'destructive'}
        onConfirm={() => confirmAction?.onConfirm()}
      />
    </>
  )
}

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
  const { theme } = useTheme()

  const createMut = useMutation({
    mutationFn: (name: string) => tagApi.createCategory({ name }),
    onSuccess: (cat) => {
      invalidate()
      onSelect(cat.name)
    },
  })

  return (
    <div
      className="flex-shrink-0 border-r border-border flex flex-col overflow-hidden bg-popover"
      style={{ width: 160 }}
    >
      <p className="flex-shrink-0 section-label" style={{ padding: '9px 14px 5px' }}>
        Categories
      </p>

      <div className="flex-1 overflow-y-auto" style={{ paddingTop: 2, paddingBottom: 2 }}>
        {categories.map((cat) => {
          const colors = getTagColor(cat.color, theme)
          const CatIcon = getCategoryIcon(cat.icon)
          const isActive = cat.name === selected
          const valueCount = parseCommonValues(cat.common_values).length

          return (
            <button
              key={cat.name}
              onClick={() => onSelect(cat.name)}
              style={{ padding: '7px 12px 7px 14px' }}
              className={`w-full flex items-center gap-2 text-left text-[12px] border-l-2 capitalize transition-colors ${
                isActive
                  ? `font-medium border-current ${colors.text} bg-muted`
                  : `text-muted-foreground border-transparent hover:bg-muted`
              }`}
            >
              <CatIcon
                className={isActive ? 'flex-shrink-0' : `flex-shrink-0 ${colors.text} opacity-60`}
                style={{ width: 13, height: 13 }}
              />
              <span className="flex-1 truncate">{cat.name}</span>
              {valueCount > 0 && (
                <span className={`text-[10px] tabular-nums flex-shrink-0 `}>{valueCount}</span>
              )}
            </button>
          )
        })}
      </div>

      <div className="flex-shrink-0 border-t border-border" style={{ padding: '7px 12px 9px' }}>
        <InlineAddRow
          variant="sidebar"
          label="New category"
          placeholder="category name"
          onAdd={(name) => createMut.mutateAsync(name)}
        />
      </div>
    </div>
  )
}

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
  const { theme } = useTheme()
  const queryClient = useQueryClient()
  const [editingName, setEditingName] = useState(false)
  const [nameInput, setNameInput] = useState(category.name)
  const [description, setDescription] = useState(category.description ?? '')

  const colors = getTagColor(category.color, theme)
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
    hasUnsavedDescRef.current = false
  }

  // Save unsaved description on unmount (dialog close or category switch)
  const descriptionRef = useRef(description)
  descriptionRef.current = description

  const categoryDescRef = useRef(category.description ?? '')
  categoryDescRef.current = category.description ?? ''

  const hasUnsavedDescRef = useRef(false)

  const categoryNameRef = useRef(category.name)
  categoryNameRef.current = category.name

  const handleDescChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setDescription(e.target.value)
    hasUnsavedDescRef.current = true
  }

  useEffect(() => {
    return () => {
      if (!hasUnsavedDescRef.current) return
      const current = descriptionRef.current.trim()
      const original = categoryDescRef.current
      if (current !== original) {
        tagApi
          .updateCategory(categoryNameRef.current, { description: current || undefined })
          .then(() => invalidateTagQueries(queryClient))
          .catch((err) => console.error('Failed to save category description:', err))
      }
    }
  }, [queryClient])

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <div
        className="border-b border-border flex-shrink-0"
        style={{ padding: '11px 14px 10px 16px' }}
      >
        <div className="flex items-start justify-between gap-2">
          <div className="flex flex-col gap-0.5 flex-1 min-w-0">
            <p className="section-label">Editing</p>
            <div className="group/catname flex items-center gap-[7px] mt-0.5">
              <Popover>
                <PopoverTrigger asChild>
                  <button
                    className="flex-shrink-0 flex items-center justify-center rounded-[5px] bg-secondary/60 hover:bg-secondary transition-colors"
                    style={{ width: 26, height: 26 }}
                    title="Change icon & color"
                  >
                    <CatIcon className={colors.text} style={{ width: 15, height: 15 }} />
                  </button>
                </PopoverTrigger>
                <PopoverContent align="start" className="w-auto p-3">
                  <p className="section-label mb-2">Icon</p>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(8, 32px)', gap: 2 }}>
                    {CATEGORY_ICON_NAMES.map((iconName) => {
                      const IconComp = CATEGORY_ICON_MAP[iconName]
                      const isSelected = category.icon === iconName
                      return (
                        <button
                          key={iconName}
                          onClick={() => updateMut.mutate({ icon: iconName })}
                          title={iconName}
                          className={`flex items-center justify-center rounded-[4px] transition-all ${
                            isSelected
                              ? 'text-foreground bg-secondary'
                              : 'text-muted-foreground hover:text-foreground hover:bg-secondary'
                          }`}
                          style={{
                            width: 32,
                            height: 32,
                            ...(isSelected
                              ? {
                                  outline: '2px solid hsl(var(--foreground) / 0.5)',
                                  outlineOffset: 1,
                                }
                              : {}),
                          }}
                        >
                          <IconComp style={{ width: 17, height: 17 }} />
                        </button>
                      )
                    })}
                  </div>
                  <div className="my-3 h-px bg-border/50" />
                  <p className="section-label mb-2">Color</p>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(8, 26px)', gap: 6 }}>
                    {PALETTE_KEYS.map((key) => {
                      const isSelected = category.color === key
                      return (
                        <button
                          key={key}
                          onClick={() => updateMut.mutate({ color: key })}
                          title={key}
                          className={`rounded-full transition-all ${
                            isSelected ? '' : 'opacity-70 hover:opacity-100 hover:scale-110'
                          } ${getDotColor(key)}`}
                          style={{
                            width: 26,
                            height: 26,
                            ...(isSelected
                              ? { outline: '2px solid hsl(var(--foreground))', outlineOffset: 3 }
                              : {}),
                          }}
                        />
                      )
                    })}
                  </div>
                </PopoverContent>
              </Popover>

              {editingName ? (
                <input
                  autoFocus
                  value={nameInput}
                  onChange={(e) => setNameInput(e.target.value)}
                  onBlur={handleNameSave}
                  onKeyDown={(e) =>
                    onInlineEditKey(e, {
                      onEnter: () => e.currentTarget.blur(),
                      onEscape: () => {
                        setEditingName(false)
                        setNameInput(category.name)
                      },
                    })
                  }
                  className={`flex-1 min-w-0 bg-transparent border-b border-primary/70 focus:outline-none font-display text-[17px] font-medium tracking-[0.04em] leading-[1.2] capitalize ${colors.text}`}
                />
              ) : (
                <span
                  onClick={() => setEditingName(true)}
                  className={`font-display text-[17px] font-medium tracking-[0.04em] leading-[1.2] capitalize cursor-text ${colors.text}`}
                >
                  {category.name}
                </span>
              )}
              {!editingName && (
                <button
                  onClick={() => setEditingName(true)}
                  className="relative target-24 opacity-0 focus-visible:opacity-100 [@media(hover:none)]:opacity-100 group-hover/catname:opacity-60 hover:!opacity-100 transition-opacity text-muted-foreground shrink-0"
                  title="Rename"
                >
                  <Pencil className="h-3 w-3" />
                </button>
              )}
            </div>
          </div>

          <div className="flex items-center shrink-0" style={{ marginTop: 12 }}>
            {!editingName && (
              <button
                onClick={() =>
                  setConfirmAction({
                    label: `Delete "${category.name}"?`,
                    detail:
                      'This will permanently remove the category and delete all its tags from every image.',
                    onConfirm: () => {
                      deleteMut.mutate()
                      setConfirmAction(null)
                    },
                  })
                }
                className="flex-shrink-0 flex items-center justify-center transition-colors hover:bg-destructive/10"
                style={{
                  width: 26,
                  height: 26,
                  background: 'transparent',
                  border: '1px solid hsl(var(--destructive) / 0.2)',
                  borderRadius: 5,
                  color: 'hsl(var(--destructive) / 0.55)',
                }}
                title={`Delete ${category.name}`}
              >
                <Trash2 style={{ width: 12, height: 12 }} />
              </button>
            )}
          </div>
        </div>

        <div style={{ marginTop: 8 }}>
          <textarea
            value={description}
            onChange={handleDescChange}
            onBlur={handleDescSave}
            onKeyDown={(e) =>
              onInlineEditKey(e, {
                onEnter: handleDescSave,
                onEscape: () => e.currentTarget.blur(),
                allowShiftEnter: true,
              })
            }
            placeholder="Add a description…"
            rows={1}
            className="w-full text-[11.5px] text-muted-foreground placeholder:text-muted-foreground bg-transparent border-b border-border/50 focus:border-primary/70 focus:outline-none focus:text-foreground resize-none py-1 transition-colors"
            style={{
              height: 28,
              lineHeight: 1.4,
              fontFamily: 'inherit',
            }}
          />
        </div>
      </div>

      <div className="flex-1 overflow-hidden flex flex-col min-h-0">
        <div className="flex-shrink-0" style={{ padding: '7px 16px 3px' }}>
          <p className="section-label">Tag Values</p>
        </div>
        <div className="flex-1 overflow-y-auto" style={{ padding: '1px 10px 8px' }}>
          <TagValueList
            categoryName={category.name}
            values={values}
            colors={colors}
            facetCounts={facetCounts}
            invalidate={invalidate}
            setConfirmAction={setConfirmAction}
          />
        </div>
      </div>
    </div>
  )
}

function TagValueList({
  categoryName,
  values,
  colors,
  facetCounts,
  invalidate,
  setConfirmAction,
}: {
  categoryName: string
  values: TagValueEntry[]
  colors: TagColor
  facetCounts: { value: string; count: number }[]
  invalidate: () => void
  setConfirmAction: (a: ConfirmAction | null) => void
}) {
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
            colors={colors}
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

      <div style={{ marginTop: 4 }}>
        <InlineAddRow
          variant="list"
          label="Add tag value"
          placeholder="tag value"
          keepOpen
          onAdd={(value) => upsertMut.mutate({ value })}
        />
      </div>
    </div>
  )
}

function TagValueRow({
  categoryName,
  entry,
  count,
  colors,
  invalidate,
  onDelete,
}: {
  categoryName: string
  entry: TagValueEntry
  count: number
  colors: TagColor
  invalidate: () => void
  onDelete: () => void
}) {
  const [editMode, setEditMode] = useState<'none' | 'name' | 'aliases'>('none')
  const [editVal, setEditVal] = useState(entry.value)
  const [aliasInput, setAliasInput] = useState('')
  // A click that ends an edit (blurring the input, or "done") lands on the row afterwards,
  // and the row's click starts a rename. Ignore row clicks within 150ms of an edit ending.
  const editEndedAt = useRef(0)

  const renameMut = useMutation({
    mutationFn: (newValue: string) => tagApi.renameTagValue(categoryName, entry.value, newValue),
    onSuccess: () => {
      invalidate()
      setEditMode('none')
    },
  })

  const upsertMut = useMutation({
    mutationFn: (aliases: string[]) => tagApi.upsertTagValue(categoryName, entry.value, aliases),
    onSuccess: () => invalidate(),
  })

  const handleRename = () => {
    const trimmed = editVal.trim()
    editEndedAt.current = Date.now()
    if (!trimmed || trimmed === entry.value) {
      setEditMode('none')
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

  const isEditing = editMode !== 'none'

  return (
    <div
      className={`group/valrow flex items-stretch border-b border-border/40 transition-colors last:border-b-0 ${
        isEditing ? 'bg-muted/50' : 'hover:bg-muted/30'
      }`}
    >
      {/* Content: name + aliases — click anywhere to edit name */}
      <div
        className="flex-1 min-w-0 py-[7px] px-[10px] cursor-text"
        onClick={() => {
          if (editMode === 'none' && Date.now() - editEndedAt.current > 150) setEditMode('name')
        }}
      >
        {editMode === 'name' ? (
          <input
            autoFocus
            value={editVal}
            onChange={(e) => setEditVal(e.target.value)}
            onBlur={handleRename}
            onKeyDown={(e) =>
              onInlineEditKey(e, {
                onEnter: () => e.currentTarget.blur(),
                onEscape: () => {
                  editEndedAt.current = Date.now()
                  setEditMode('none')
                  setEditVal(entry.value)
                },
              })
            }
            className="w-full bg-transparent border-b border-primary/70 focus:outline-none text-[13px] font-medium text-foreground capitalize"
          />
        ) : (
          <span
            className={`text-left text-[13px] font-medium capitalize leading-[1.3] ${colors.text}`}
          >
            {entry.value}
          </span>
        )}

        {editMode !== 'name' && editMode !== 'aliases' && (
          <button
            onClick={(e) => {
              e.stopPropagation()
              setEditMode('aliases')
            }}
            className={`text-left text-[10.5px] leading-[1.3] mt-0.5 block w-full transition-colors ${
              entry.aliases.length > 0
                ? 'text-muted-foreground capitalize italic hover:text-foreground'
                : 'italic text-muted-foreground hover:text-foreground'
            }`}
          >
            {entry.aliases.length > 0 ? entry.aliases.join(', ') : 'No aliases'}
          </button>
        )}

        {editMode === 'aliases' && (
          <div style={{ marginTop: 4 }}>
            {entry.aliases.length > 0 && (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginBottom: 5 }}>
                {entry.aliases.map((alias) => (
                  <span
                    key={alias}
                    className={`inline-flex items-center gap-[3px] text-[11px] border capitalize ${colors.bg} ${colors.border} ${colors.text}`}
                    style={{ padding: '2px 7px', borderRadius: 999 }}
                  >
                    {alias}
                    <button
                      onClick={() => removeAlias(alias)}
                      className="opacity-50 hover:opacity-100 transition-opacity"
                      style={{ marginLeft: 1 }}
                    >
                      <X style={{ width: 9, height: 9 }} />
                    </button>
                  </span>
                ))}
              </div>
            )}

            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <input
                autoFocus
                value={aliasInput}
                onChange={(e) => setAliasInput(e.target.value)}
                onKeyDown={(e) =>
                  onInlineEditKey(e, {
                    onEnter: addAlias,
                    onEscape: () => {
                      editEndedAt.current = Date.now()
                      setEditMode('none')
                    },
                  })
                }
                placeholder="add alias…"
                className="flex-1 max-w-[155px] bg-transparent border-b border-border focus:border-primary/70 text-[11.5px] text-foreground placeholder:text-muted-foreground focus:outline-none py-0.5 transition-colors"
              />
              <button
                onClick={() => {
                  editEndedAt.current = Date.now()
                  setEditMode('none')
                }}
                className="text-[10.5px] text-muted-foreground italic hover:text-foreground transition-colors"
                style={{ opacity: 0.7 }}
              >
                done
              </button>
            </div>
          </div>
        )}
      </div>

      <div className="w-[54px] shrink-0 flex items-center justify-end gap-1 px-2">
        {editMode !== 'name' && (
          <button
            onClick={() => setEditMode('name')}
            className="relative target-24 opacity-0 focus-visible:opacity-100 [@media(hover:none)]:opacity-100 group-hover/valrow:opacity-50 hover:!opacity-100 transition-opacity text-muted-foreground shrink-0"
            title="Rename"
          >
            <Pencil className="h-2.5 w-2.5" />
          </button>
        )}
        {count > 0 && (
          <span className="text-[11px] text-muted-foreground tabular-nums">{count}</span>
        )}
        <button
          onClick={onDelete}
          className="relative target-24 flex items-center justify-center rounded-[3px] transition-colors hover:bg-destructive/10"
          style={{
            width: 18,
            height: 18,
            color: 'hsl(var(--destructive) / 0.45)',
            padding: 0,
          }}
          title="Delete"
        >
          <Trash2 style={{ width: 11, height: 11 }} />
        </button>
      </div>
    </div>
  )
}

const INLINE_ADD_STYLES = {
  sidebar: {
    row: 'flex items-center gap-1',
    rowStyle: undefined,
    input:
      'flex-1 min-w-0 bg-secondary border border-border rounded px-1.5 py-0.5 text-[11.5px] text-foreground placeholder:text-muted-foreground',
  },
  list: {
    row: 'flex items-center gap-1.5 rounded-[5px]',
    rowStyle: {
      padding: '5px 8px',
      background: 'hsl(var(--muted))',
      border: '1px solid hsl(var(--border))',
    },
    input:
      'flex-1 min-w-0 bg-transparent text-[13px] text-foreground placeholder:text-muted-foreground focus:outline-none',
  },
} as const

/**
 * "+ label" button that turns into an input with confirm/cancel. By default it closes once
 * `onAdd` resolves (and stays open if it rejects); `keepOpen` clears the input for the next entry.
 */
function InlineAddRow({
  variant,
  label,
  placeholder,
  onAdd,
  keepOpen = false,
}: {
  variant: keyof typeof INLINE_ADD_STYLES
  label: string
  placeholder: string
  onAdd: (value: string) => unknown
  keepOpen?: boolean
}) {
  const [adding, setAdding] = useState(false)
  const [value, setValue] = useState('')
  const styles = INLINE_ADD_STYLES[variant]

  const cancel = () => {
    setAdding(false)
    setValue('')
  }

  const submit = async () => {
    const trimmed = value.trim()
    if (!trimmed) return
    if (keepOpen) {
      onAdd(trimmed)
      setValue('')
      return
    }
    try {
      await onAdd(trimmed)
      cancel()
    } catch {
      // The mutation holds the error; keep the input so the user can fix it.
    }
  }

  if (!adding) {
    return (
      <button
        onClick={() => setAdding(true)}
        className="flex items-center gap-1.5 text-[11.5px] text-muted-foreground hover:text-muted-foreground transition-colors"
      >
        <Plus className="h-[11px] w-[11px]" />
        {label}
      </button>
    )
  }

  return (
    <div className={styles.row} style={styles.rowStyle}>
      <input
        autoFocus
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => onInlineEditKey(e, { onEnter: submit, onEscape: cancel })}
        placeholder={placeholder}
        className={styles.input}
      />
      <button
        onClick={submit}
        aria-label="Save"
        className="p-0.5 text-primary hover:text-primary/80"
      >
        <Check style={{ width: 11, height: 11 }} />
      </button>
      <button
        onClick={cancel}
        aria-label="Cancel"
        className="p-0.5 text-muted-foreground hover:text-foreground"
      >
        <X style={{ width: 11, height: 11 }} />
      </button>
    </div>
  )
}
