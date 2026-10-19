import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Loader2 } from 'lucide-react'
import { imageApi } from '@/lib/api'
import { gridLabel } from '@/lib/bulkEdit'
import { BulkEditControls } from '@/components/import/BulkEditControls'
import type { ParsedTagVocab } from '@/components/import/types'
import type { useBulkImageEdit } from '@/hooks/useBulkImageEdit'
import type { ImageScopeFacets, ImageScopeFilter, ScopeFacetCount } from '@/types'

export const SCOPE_FACETS_KEY = 'scope-facets'

type FacetKind = 'image_type' | 'grid' | 'subgroup' | 'tags'

/** The one facet value the panel's edits are narrowed to, if any */
interface Picked {
  kind: FacetKind
  value: string | null
  count: number
}

const GRID_NAMES: Record<string, string> = {
  square: 'Square',
  hex: 'Hex',
  gridded: 'Any gridded',
  gridless: 'Gridless',
  unknown: 'Unknown',
}

const FACET_LABELS: Record<FacetKind, (value: string | null) => string> = {
  image_type: (value) => (value === 'scene' ? 'Scenes' : 'Maps'),
  grid: (value) => GRID_NAMES[value ?? ''] ?? String(value),
  subgroup: (value) => value ?? 'No subgroup',
  tags: (value) => value ?? '',
}

function facetLabel(kind: FacetKind, value: string | null) {
  return FACET_LABELS[kind](value)
}

const FILTERS: Record<FacetKind, (value: string | null) => ImageScopeFilter> = {
  image_type: (value) => ({ image_type: value === 'scene' ? 'scene' : 'battlemap' }),
  grid: (value) => ({ grid: value as ImageScopeFilter['grid'] }),
  subgroup: (value) => ({ subgroup: value }),
  tags: (value) => {
    const [category, ...rest] = (value ?? '').split(':')
    return { tag: { category, value: rest.join(':') } }
  },
}

function toFilter(picked: Picked | null) {
  if (!picked) return {}
  return FILTERS[picked.kind](picked.value)
}

const n = (count: number) => count.toLocaleString()

interface BulkPanelProps {
  /** The import's groups: the panel works on all of their images */
  groupIds: number[]
  vocab: ParsedTagVocab[]
  bulk: ReturnType<typeof useBulkImageEdit>
}

/**
 * The All view of a large import (import review above LARGE_REVIEW_IMAGES): counts from
 * the server instead of a grid of every file, and bulk edits applied to the whole import
 * or to one facet of it, resolved on the server.
 */
export function BulkPanel({ groupIds, vocab, bulk }: BulkPanelProps) {
  const [picked, setPicked] = useState<Picked | null>(null)
  const idsKey = useMemo(() => groupIds.join(','), [groupIds])
  const { data: facets, isLoading } = useQuery({
    queryKey: [SCOPE_FACETS_KEY, idsKey],
    queryFn: () => imageApi.facets({ group_ids: groupIds }),
  })

  if (isLoading || !facets) {
    return (
      <div className="flex-1 flex items-center justify-center text-muted-foreground">
        <Loader2 className="h-5 w-5 animate-spin" aria-label="Counting images" />
      </div>
    )
  }

  const count = picked?.count ?? facets.total
  const scope = { group_ids: groupIds, filter: toFilter(picked) }
  const edit = (change: Parameters<typeof bulk.requestScope>[2]) =>
    bulk.requestScope(scope, count, change)

  return (
    <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
      <h3 className="font-display text-lg font-semibold">
        {n(facets.total)} images in {n(groupIds.length)} groups
      </h3>
      <p className="text-sm text-muted-foreground mt-1 max-w-prose">
        Too many to show at once. Open a group from the list to review it, or change many images
        here: everything, or only the ones you pick below.
      </p>

      <FacetChoices facets={facets} picked={picked} onPick={setPicked} />

      <div className="sticky bottom-0 mt-5 -mx-5 px-5 py-3 border-t border-border/40 bg-card flex flex-wrap items-center gap-2">
        <span className="text-sm mr-1" role="status">
          Change{' '}
          {picked ? `the ${n(count)} ${facetLabel(picked.kind, picked.value)}` : `all ${n(count)}`}{' '}
          images:
        </span>
        <BulkEditControls
          vocab={vocab}
          existingSubgroups={facets.subgroup.flatMap((s) => (s.value ? [s.value] : []))}
          onAddTag={(tag) => edit({ addTags: [tag], label: `Add tag "${tag.value}"` })}
          onSetGrid={(gridded, gridType) =>
            edit({ changes: { gridded, grid_type: gridType }, label: gridLabel(gridded, gridType) })
          }
          onSetImageType={(v) =>
            edit({
              changes: { image_type: v },
              label: `Set type to ${v === 'scene' ? 'scene' : 'map'}`,
            })
          }
          onSetSubgroup={(v) => {
            const subgroup = v.trim() || null
            edit({
              changes: { subgroup },
              label: subgroup ? `Set subgroup to "${subgroup}"` : 'Clear subgroup',
            })
          }}
        />
      </div>
    </div>
  )
}

const SECTIONS: { kind: FacetKind; title: string }[] = [
  { kind: 'image_type', title: 'Type' },
  { kind: 'grid', title: 'Grid' },
  { kind: 'subgroup', title: 'Subgroup' },
  { kind: 'tags', title: 'Tags' },
]

function FacetChoices({
  facets,
  picked,
  onPick,
}: {
  facets: ImageScopeFacets
  picked: Picked | null
  onPick: (p: Picked | null) => void
}) {
  return (
    <div className="mt-5 space-y-4" role="group" aria-label="Which images to change">
      <Chip
        label="Everything"
        count={facets.total}
        pressed={!picked}
        onClick={() => onPick(null)}
      />
      {SECTIONS.map(({ kind, title }) => {
        const counts = facets[kind].filter((c) => c.count > 0)
        if (counts.length === 0) return null
        return (
          <section key={kind}>
            <h4 className="section-label mb-1.5">{title}</h4>
            <div className="flex flex-wrap gap-1.5">
              {counts.map((c: ScopeFacetCount) => (
                <Chip
                  key={c.value ?? '∅'}
                  label={facetLabel(kind, c.value)}
                  count={c.count}
                  pressed={picked?.kind === kind && picked.value === c.value}
                  onClick={() => onPick({ kind, value: c.value, count: c.count })}
                />
              ))}
            </div>
          </section>
        )
      })}
    </div>
  )
}

function Chip({
  label,
  count,
  pressed,
  onClick,
}: {
  label: string
  count: number
  pressed: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      aria-pressed={pressed}
      onClick={onClick}
      className={`h-7 px-2.5 rounded-full border text-xs flex items-center gap-1.5 transition-colors ${
        pressed
          ? 'border-primary bg-primary/10 text-primary'
          : 'border-border text-muted-foreground hover:text-foreground hover:bg-secondary'
      }`}
    >
      {label}
      <span className="tabular-nums">{n(count)}</span>
    </button>
  )
}
