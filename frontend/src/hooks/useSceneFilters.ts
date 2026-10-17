import { useCallback, useMemo, useState } from 'react'
import type { FilterOptionGroup } from '@/components/FilterMenuContent'
import {
  applyFileFilter,
  buildTagFilterGroups,
  EMPTY_FILTER,
  type FileFilter,
} from '@/components/import/fileFilter'
import { filenameStem } from '@/lib/format'
import type { Image } from '@/types'

export interface SceneSection {
  label: string
  images: Image[]
}

const mediaLabel = (m: string) => (m === 'image' ? 'Images' : m === 'video' ? 'Videos' : m)

const matchesSceneText = (scene: Image, text: string) =>
  scene.name.toLowerCase().includes(text) ||
  !!scene.subgroup?.toLowerCase().includes(text) ||
  filenameStem(scene.filename).toLowerCase().includes(text)

function buildSceneFilterGroups(scenes: Image[], subgroups: string[]): FilterOptionGroup[] {
  const groups: FilterOptionGroup[] = []
  if (subgroups.length > 0) {
    groups.push({
      id: 'subgroup',
      label: 'Variant',
      type: 'subgroup',
      options: subgroups.map((sv) => ({
        filterValue: sv,
        label: sv,
        filterLabel: sv,
        count: scenes.filter((v) => v.subgroup === sv).length,
      })),
    })
  }
  const mediaTypes = [...new Set(scenes.map((v) => v.media_type ?? 'image'))]
  if (mediaTypes.length > 1) {
    groups.push({
      id: 'media_type',
      label: 'Media',
      type: 'media_type',
      options: mediaTypes.map((m) => ({
        filterValue: m,
        label: mediaLabel(m),
        filterLabel: `media: ${mediaLabel(m)}`,
        count: scenes.filter((v) => (v.media_type ?? 'image') === m).length,
      })),
    })
  }
  return [...groups, ...buildTagFilterGroups(scenes)]
}

/** Scenes grouped by subgroup in first-seen order; scenes without one go under "Other". */
export function partitionBySubgroup(scenes: Image[]): SceneSection[] {
  const groups = new Map<string, Image[]>()
  for (const v of scenes) {
    const key = v.subgroup || 'Other'
    groups.set(key, [...(groups.get(key) ?? []), v])
  }
  if (groups.size <= 1) return [{ label: [...groups.keys()][0] ?? 'All scenes', images: scenes }]
  return [...groups].map(([label, images]) => ({ label, images }))
}

/** Client-side search, type toggle and filter-menu state for the image viewer's scene panel. */
export function useSceneFilters(scenes: Image[] | undefined) {
  const [filter, setFilter] = useState<FileFilter>(EMPTY_FILTER)
  const all = useMemo(() => scenes ?? [], [scenes])

  const subgroups = useMemo(
    () => [...new Set(all.map((v) => v.subgroup).filter((sv): sv is string => sv != null))].sort(),
    [all],
  )

  const filterGroups = useMemo(
    () => (all.length > 1 ? buildSceneFilterGroups(all, subgroups) : []),
    [all, subgroups],
  )

  const hasMixedTypes = useMemo(
    () => all.length > 1 && new Set(all.map((v) => v.image_type ?? 'battlemap')).size > 1,
    [all],
  )

  const filtered = useMemo(
    // Whitespace-only search is ignored, but otherwise matched as typed.
    () =>
      applyFileFilter(
        all,
        { ...filter, text: filter.text.trim() ? filter.text : '' },
        matchesSceneText,
      ),
    [all, filter],
  )

  const sections = useMemo(() => partitionBySubgroup(filtered), [filtered])

  const reset = useCallback(() => setFilter(EMPTY_FILTER), [])

  return {
    filter,
    setFilter,
    reset,
    subgroups,
    filterGroups,
    hasMixedTypes,
    filtered,
    sections,
  }
}
