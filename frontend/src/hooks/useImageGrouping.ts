import { useMemo } from 'react'
import type { Image, ImageGroup, SortBy, SortDir, Tag } from '@/types'

interface UseImageGroupingOptions {
  images: Image[]
  scores?: Record<number, number>
  sortBy?: SortBy
  sortDir?: SortDir
}

export function useImageGrouping({
  images,
  scores,
  sortBy = 'created_at',
  sortDir = 'desc',
}: UseImageGroupingOptions): ImageGroup[] {
  return useMemo(() => {
    // Bucket images by group
    const grouped = new Map<number, Image[]>()
    const ungrouped: Image[] = []

    for (const img of images) {
      if (img.group_id != null) {
        const bucket = grouped.get(img.group_id)
        if (bucket) {
          bucket.push(img)
        } else {
          grouped.set(img.group_id, [img])
        }
      } else {
        ungrouped.push(img)
      }
    }

    const result: ImageGroup[] = []

    // Process variant groups
    for (const [groupId, groupImages] of grouped) {
      result.push(buildGroup(groupId, groupImages, scores))
    }

    // Ungrouped images become single-item groups
    for (const img of ungrouped) {
      result.push({
        groupId: null,
        baseName: img.name,
        author: img.author,
        heroImage: img,
        mosaicImages: [],
        totalScenes: 1,
        matchingCount: 1,
        bestScore: scores?.[img.id] ?? null,
        aggregatedTags: img.tags,
      })
    }

    // Sort groups by the requested field
    if (sortBy === 'relevance' && scores) {
      result.sort((a, b) => (b.bestScore ?? 0) - (a.bestScore ?? 0))
    } else if (sortBy === 'created_at') {
      result.sort((a, b) => {
        const aDate = a.heroImage.created_at ?? ''
        const bDate = b.heroImage.created_at ?? ''
        return sortDir === 'desc' ? bDate.localeCompare(aDate) : aDate.localeCompare(bDate)
      })
    } else {
      // name sort
      result.sort((a, b) =>
        sortDir === 'desc'
          ? b.baseName.localeCompare(a.baseName)
          : a.baseName.localeCompare(b.baseName),
      )
    }

    return result
  }, [images, scores, sortBy, sortDir])
}

function buildGroup(
  groupId: number,
  groupImages: Image[],
  scores?: Record<number, number>,
): ImageGroup {
  // Sort by score descending if available
  const sorted = [...groupImages]
  if (scores) {
    sorted.sort((a, b) => (scores[b.id] ?? 0) - (scores[a.id] ?? 0))
  }

  const heroImage = sorted[0]
  const remaining = sorted.slice(1)
  const mosaicImages = remaining.slice(0, 5)

  const bestScore = scores ? Math.max(...groupImages.map((img) => scores[img.id] ?? 0)) : null

  // Aggregate tags (deduplicated by category:value)
  const tagSet = new Set<string>()
  const aggregatedTags: Tag[] = []
  for (const img of groupImages) {
    for (const tag of img.tags) {
      const key = `${tag.category}:${tag.value}`
      if (!tagSet.has(key)) {
        tagSet.add(key)
        aggregatedTags.push(tag)
      }
    }
  }

  // True total comes from the backend property; fall back to matching count
  const totalScenes = heroImage.group_image_count ?? groupImages.length

  return {
    groupId,
    baseName: heroImage.group_name || heroImage.name,
    author: heroImage.author,
    heroImage,
    mosaicImages,
    totalScenes,
    matchingCount: groupImages.length,
    bestScore,
    aggregatedTags,
  }
}
