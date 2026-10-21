/**
 * The import dialog's finished view: what an import did, and what to do about
 * it (design/frontend.md "Imports"; item states and actions in
 * design/ingestion.md §4.1, §6, §7). ImportDialog shows it in place of the
 * progress view once the job finishes, in the same frame.
 *
 * Sections, each shown only when it has entries: groups, problems (grouped by
 * reason, with retry), files already in the library (with "Import as new
 * copy"), and skipped files (with previews and "Include" for those Auto sorted
 * out and still holds). Opens on problems when there are any, else on files Auto
 * skipped.
 * Actions: undo the whole import, review its groups in the editor (also what
 * clicking a group does, starting on that group), and Done, which closes the
 * report and clears a finished import from the activity list.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useVirtualizer } from '@tanstack/react-virtual'
import { Loader2, Undo2 } from 'lucide-react'
import { toast } from 'sonner'
import { getThumbnailUrlById, importPreviewUrl } from '@/lib/api/urls'
import { getImportManager } from '@/lib/import/ImportManager'
import { useImportJob } from '@/lib/import/useImports'
import type {
  ImportGroupSummary,
  ImportItem,
  ImportJobSummary,
  ItemState,
} from '@/lib/import/types'
import { ConfirmOverlay, ImportFrame, TextButton } from './ImportFrame'
import { GroupLedger } from './GroupLedger'
import { isFinished, outcomeText, plural } from './format'

type Section = 'groups' | 'failed' | 'duplicate' | 'skipped'

const SECTION_LABEL: Record<Section, string> = {
  groups: 'Groups',
  failed: 'Problems',
  duplicate: 'Already in library',
  skipped: 'Skipped',
}

interface ResultViewProps {
  jobId: string
  open: boolean
  onClose: () => void
  /** Open every group this import added to in the group editor, optionally on one of them. */
  onReviewGroups?: (imageGroupIds: number[], startGroupId?: number) => void
  /** Called after the import was undone (its images deleted). */
  onUndone?: () => void
}

/** Groups always; the other sections only when they have entries. */
function sectionsFor(job: ImportJobSummary | undefined): Section[] {
  const counts = job?.counts
  const optional = ['failed', 'duplicate', 'skipped'] as const
  return ['groups', ...optional.filter((s) => counts?.[s])]
}

/** The author every group shares, if they all share one. */
function sharedAuthorOf(groups: ImportGroupSummary[]): string | null {
  const authors = new Set(groups.map((g) => g.author))
  return authors.size === 1 ? [...authors][0] : null
}

/** "454 imported, 3 already in your library in 68 groups · caeora" */
function statusLine(
  job: ImportJobSummary,
  groups: ImportGroupSummary[],
  sharedAuthor: string | null,
): string {
  const prefix =
    job.status === 'cancelled' ? 'Cancelled. ' : isFinished(job) ? '' : 'Still running. '
  const skipped = job.counts.skipped ? `, ${job.counts.skipped.toLocaleString()} skipped` : ''
  // When every group has the same author, say it once here rather than on every row
  const where = groups.length ? ` in ${plural(groups.length, 'group')}` : ''
  const author = sharedAuthor ? ` · ${sharedAuthor}` : ''
  return `${prefix}${outcomeText(job.counts)}${skipped}${where}${author}`
}

export function ResultView({ jobId, open, onClose, onReviewGroups, onUndone }: ResultViewProps) {
  const manager = getImportManager()
  const { job, detail } = useImportJob(jobId, { watch: open })
  // null until the user picks a tab: then the report opens on problems if there are any
  const [section, setSection] = useState<Section | null>(null)
  const [confirmingUndo, setConfirmingUndo] = useState(false)
  const [busy, setBusy] = useState(false)
  const [itemsVersion, setItemsVersion] = useState(0)

  useEffect(() => {
    if (open) setSection(null)
  }, [open, jobId])

  const counts = job?.counts
  const sections = sectionsFor(job)
  const fallback: Section = job?.counts.failed
    ? 'failed'
    : job?.counts.sorted_out
      ? 'skipped'
      : 'groups'
  const active = section && sections.includes(section) ? section : fallback
  const reviewIds = detail?.reviewable_group_ids ?? []

  /** Run an item action, reload the lists, and toast what the server says it did */
  const act = async <T,>(action: () => Promise<T>, done?: (result: T) => string) => {
    setBusy(true)
    try {
      const result = await action()
      setItemsVersion((v) => v + 1)
      if (done) toast.success(done(result))
    } catch {
      toast.error("That didn't work", { description: 'The server could not be reached.' })
    } finally {
      setBusy(false)
    }
  }

  const undo = () =>
    act(async () => {
      const deleted = await manager.undo(jobId)
      setConfirmingUndo(false)
      onUndone?.()
      onClose()
      toast.success(`Import undone. ${plural(deleted, 'image')} removed.`)
    })

  const groups = detail?.groups ?? []
  const sharedAuthor = sharedAuthorOf(groups)
  const finished = !!job && isFinished(job)

  const done = () => {
    if (!finished || job.dismissed) return onClose()
    void act(async () => {
      await manager.dismiss(jobId)
      onClose()
    })
  }

  return (
    <ImportFrame
      open={open}
      onClose={onClose}
      title={job?.label ?? 'Import report'}
      status={job ? statusLine(job, groups, sharedAuthor) : 'Loading'}
      footer={
        <>
          {/* A linked folder's maps leave with "Unlink", not Undo */}
          {!job?.linked && (
            <TextButton
              tone="outline-danger"
              onClick={() => setConfirmingUndo(true)}
              disabled={busy || !job}
            >
              <Undo2 className="h-3.5 w-3.5" aria-hidden />
              Undo import
            </TextButton>
          )}
          <div className="ml-auto flex gap-2">
            <TextButton
              tone="outline"
              onClick={done}
              disabled={busy}
              title={
                finished
                  ? 'Close, and clear this import from the activity list'
                  : 'Close the report'
              }
            >
              Done
            </TextButton>
            {onReviewGroups && reviewIds.length > 0 && (
              <TextButton tone="solid" onClick={() => onReviewGroups(reviewIds)}>
                Review in editor
              </TextButton>
            )}
          </div>
        </>
      }
    >
      {sections.length > 1 && (
        <div className="px-6 pb-3 shrink-0">
          <div
            className="inline-flex rounded-md overflow-hidden border border-border"
            role="tablist"
          >
            {sections.map((s) => (
              <button
                key={s}
                role="tab"
                aria-selected={active === s}
                onClick={() => setSection(s)}
                className={`inline-flex items-center gap-2 h-8 px-3 text-xs border-r border-border last:border-r-0 transition-colors focus-visible:outline-offset-[-2px] ${
                  active === s
                    ? 'bg-secondary text-foreground'
                    : 'text-muted-foreground hover:text-foreground hover:bg-secondary/50'
                }`}
              >
                {SECTION_LABEL[s]}
                <span
                  className={`px-1.5 py-px rounded-full text-3xs font-medium tabular-nums ${
                    s === 'failed'
                      ? 'bg-destructive/15 text-destructive'
                      : 'bg-primary/15 text-primary'
                  }`}
                >
                  {(s === 'groups' ? job?.group_count : counts?.[s])?.toLocaleString()}
                </span>
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="h-[min(28rem,55vh)] flex flex-col border-t border-border/30 pt-2">
        {active === 'groups' && (
          <GroupLedger
            groups={groups}
            showAuthor={!sharedAuthor}
            onOpenGroup={
              onReviewGroups ? (groupId) => onReviewGroups(reviewIds, groupId) : undefined
            }
          />
        )}
        {active === 'failed' && (
          <ItemList
            key={`failed-${itemsVersion}`}
            jobId={jobId}
            state="failed"
            groupBy={(i) => i.error_reason ?? 'Unknown problem'}
            headerAction={(members) => (
              <TextButton
                onClick={() =>
                  void act(
                    () => manager.retry(jobId, idsOf(members)),
                    (n) => `Retrying ${plural(n, 'file')}`,
                  )
                }
                disabled={busy}
              >
                Retry
              </TextButton>
            )}
          />
        )}
        {active === 'duplicate' && (
          <ItemList
            key={`duplicate-${itemsVersion}`}
            jobId={jobId}
            state="duplicate"
            groupBy={(i) =>
              i.duplicate_tier === 'pixels'
                ? 'Same picture as a file already in your library'
                : 'Identical to a file already in your library'
            }
            thumbnailUrlOf={(i) =>
              i.duplicate_of_image_id === null ? null : getThumbnailUrlById(i.duplicate_of_image_id)
            }
            headerAction={(members) => (
              <TextButton
                onClick={() =>
                  void act(
                    () => manager.importAsCopy(jobId, idsOf(members)),
                    (n) => `Importing ${plural(n, 'new copy', 'new copies')}`,
                  )
                }
                disabled={busy}
                title="Import these as separate images, even though they match"
              >
                Import as new copies
              </TextButton>
            )}
          />
        )}
        {active === 'skipped' && (
          <ItemList
            key={`skipped-${itemsVersion}`}
            jobId={jobId}
            state="skipped"
            groupBy={(i) => i.error_reason ?? 'Skipped'}
            thumbnailUrlOf={(i) => (i.has_preview ? importPreviewUrl(i) : null)}
            headerAction={(members) => {
              // Expired skips can't be included: their bytes are gone
              const includable = members.filter((m) => m.error_kind === 'sorted_out')
              return (
                includable.length > 0 && (
                  <TextButton
                    onClick={() =>
                      void act(
                        () => manager.include(idsOf(includable)),
                        (result) => `Importing ${plural(result.affected, 'image')}`,
                      )
                    }
                    disabled={busy}
                    title="Auto skipped these. Import them after all"
                  >
                    Include
                  </TextButton>
                )
              )
            }}
          />
        )}
      </div>

      {confirmingUndo && job && (
        <ConfirmOverlay
          title="Undo this import?"
          detail={
            <>
              This deletes the {plural(job.counts.done, 'image')} this import added to your library,
              and any groups it created. This can't be undone.
            </>
          }
          confirmLabel="Delete imported images"
          tone="danger"
          busy={busy}
          onCancel={() => setConfirmingUndo(false)}
          onConfirm={() => void undo()}
        />
      )}
    </ImportFrame>
  )
}

// Item lists

type Row =
  | { kind: 'header'; key: string; title: string; members: ImportItem[] }
  | { kind: 'item'; key: string; item: ImportItem }

const PAGE = 500

const idsOf = (items: ImportItem[]) => items.map((i) => i.id)

/**
 * Items in one state, grouped under ruled headers (e.g. by error reason).
 * Loads a page at a time; virtualised so thousands of rows stay cheap.
 */
function ItemList({
  jobId,
  state,
  groupBy,
  headerAction,
  thumbnailUrlOf,
}: {
  jobId: string
  state: ItemState
  groupBy: (item: ImportItem) => string
  /** An action on a header's items */
  headerAction?: (members: ImportItem[]) => React.ReactNode
  /** A thumbnail for the row, or null for none */
  thumbnailUrlOf?: (item: ImportItem) => string | null
}) {
  const [items, setItems] = useState<ImportItem[]>([])
  const [nextAfter, setNextAfter] = useState<number | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)

  const load = useCallback(
    async (after?: number) => {
      setLoading(true)
      setError(false)
      try {
        const page = await getImportManager().listItems(jobId, {
          state: [state],
          after,
          limit: PAGE,
        })
        setItems((prev) => (after ? [...prev, ...page.items] : page.items))
        setNextAfter(page.next_after)
      } catch {
        setError(true)
      } finally {
        setLoading(false)
      }
    },
    [jobId, state],
  )

  useEffect(() => {
    void load()
  }, [load])

  const rows = useMemo<Row[]>(() => {
    const groups = new Map<string, ImportItem[]>()
    for (const item of items) {
      const key = groupBy(item)
      groups.set(key, [...(groups.get(key) ?? []), item])
    }
    return [...groups].flatMap(([title, members]) => [
      { kind: 'header' as const, key: `h:${title}`, title, members },
      ...members.map((item) => ({ kind: 'item' as const, key: `i:${item.id}`, item })),
    ])
  }, [items, groupBy])
  // Rows without a thumbnail keep its space when others have one, so names line up
  const hasThumbnails = useMemo(
    () => !!thumbnailUrlOf && items.some((i) => thumbnailUrlOf(i) !== null),
    [items, thumbnailUrlOf],
  )

  const scrollRef = useRef<HTMLDivElement>(null)
  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: (i) => (rows[i].kind === 'header' || hasThumbnails ? 44 : 30),
    overscan: 12,
    initialRect: { width: 640, height: 480 }, // render rows before the first measure
  })

  if (error) {
    return (
      <div className="px-6 py-8 text-center text-xs text-muted-foreground">
        Couldn't load this list.{' '}
        <button className="text-primary hover:underline" onClick={() => void load()}>
          Try again
        </button>
      </div>
    )
  }

  return (
    <div ref={scrollRef} className="flex-1 min-h-0 overflow-y-auto px-6 pb-3">
      <div style={{ height: virtualizer.getTotalSize(), position: 'relative' }}>
        {virtualizer.getVirtualItems().map((v) => {
          const row = rows[v.index]
          const style = {
            position: 'absolute' as const,
            top: v.start,
            left: 0,
            right: 0,
            height: v.size,
          }
          if (row.kind === 'header') {
            return (
              <div
                key={row.key}
                style={style}
                className="flex items-center gap-3 border-b border-border/40"
              >
                <span className="text-xs font-medium text-foreground truncate">{row.title}</span>
                <span className="font-mono text-2xs text-muted-foreground tabular-nums">
                  {row.members.length.toLocaleString()}
                </span>
                <span className="ml-auto">{headerAction?.(row.members)}</span>
              </div>
            )
          }
          const thumbUrl = thumbnailUrlOf?.(row.item) ?? null
          return (
            <div
              key={row.key}
              style={style}
              className="flex items-center gap-3 border-b border-border/20 min-w-0"
            >
              {hasThumbnails && (
                <span className="h-8 w-8 shrink-0 rounded bg-secondary overflow-hidden">
                  {thumbUrl !== null && (
                    <img
                      src={thumbUrl}
                      alt=""
                      loading="lazy"
                      className="h-full w-full object-cover"
                    />
                  )}
                </span>
              )}
              <span
                className="font-mono text-2xs text-muted-foreground truncate"
                title={row.item.relative_path}
              >
                {row.item.relative_path}
              </span>
            </div>
          )
        })}
      </div>
      {loading && (
        <div className="flex justify-center py-4">
          <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
        </div>
      )}
      {!loading && nextAfter !== null && (
        <div className="flex justify-center py-3">
          <TextButton onClick={() => void load(nextAfter)}>Show more</TextButton>
        </div>
      )}
    </div>
  )
}
