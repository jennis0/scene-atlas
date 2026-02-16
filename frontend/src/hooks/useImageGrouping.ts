import { useMemo } from 'react'
import type { Image, ImageGroup, Tag } from '@/types'

interface UseImageGroupingOptions {
  images: Image[]
  allImages?: Image[]
  scores?: Record<number, number>
}

export function useImageGrouping({
  images,
  allImages,
  scores,
}: UseImageGroupingOptions): ImageGroup[] {
  return useMemo(() => {
    // Build a map of true group sizes from allImages
    const trueGroupSizes = new Map<number, number>()
    if (allImages) {
      for (const img of allImages) {
        if (img.variant_group_id != null) {
          trueGroupSizes.set(
            img.variant_group_id,
            (trueGroupSizes.get(img.variant_group_id) ?? 0) + 1
          )
        }
      }
    }

    // Bucket images by variant_group_id
    const grouped = new Map<number, Image[]>()
    const ungrouped: Image[] = []

    for (const img of images) {
      if (img.variant_group_id != null) {
        const bucket = grouped.get(img.variant_group_id)
        if (bucket) {
          bucket.push(img)
        } else {
          grouped.set(img.variant_group_id, [img])
        }
      } else {
        ungrouped.push(img)
      }
    }

    const result: ImageGroup[] = []

    // Process variant groups
    for (const [groupId, groupImages] of grouped) {
      result.push(buildGroup(groupId, groupImages, trueGroupSizes, scores))
    }

    // Ungrouped images become single-item groups
    for (const img of ungrouped) {
      result.push({
        groupId: null,
        baseName: img.name,
        author: img.author,
        heroImage: img,
        mosaicImages: [],
        totalVariants: 1,
        matchingCount: 1,
        bestScore: scores?.[img.id] ?? null,
        aggregatedTags: img.tags,
      })
    }

    // Sort: by score descending if semantic, else alphabetical
    if (scores) {
      result.sort((a, b) => (b.bestScore ?? 0) - (a.bestScore ?? 0))
    } else {
      result.sort((a, b) => a.baseName.localeCompare(b.baseName))
    }

    return result
  }, [images, allImages, scores])
}

function buildGroup(
  groupId: number,
  groupImages: Image[],
  trueGroupSizes: Map<number, number>,
  scores?: Record<number, number>
): ImageGroup {
  // Sort by score descending if available
  const sorted = [...groupImages]
  if (scores) {
    sorted.sort((a, b) => (scores[b.id] ?? 0) - (scores[a.id] ?? 0))
  }

  const heroImage = sorted[0]
  const remaining = sorted.slice(1)
  const mosaicImages = remaining.slice(0, 5)

  const bestScore = scores
    ? Math.max(...groupImages.map((img) => scores[img.id] ?? 0))
    : null

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

  return {
    groupId,
    baseName: heroImage.name,
    author: heroImage.author,
    heroImage,
    mosaicImages,
    totalVariants: trueGroupSizes.get(groupId) ?? groupImages.length,
    matchingCount: groupImages.length,
    bestScore,
    aggregatedTags,
  }
}
