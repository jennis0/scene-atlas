import { createContext, useContext, useMemo, useCallback } from 'react'
import { useQuery } from '@tanstack/react-query'
import { tagApi } from '@/lib/api'
import { getTagColor } from '@/components/import/tagColors'
import type { TagColor } from '@/components/import/tagColors'
import type { TagCategory } from '@/types'

type CategoryColorMap = Map<string, string>

const TagColorContext = createContext<CategoryColorMap>(new Map())

export function TagColorProvider({ children }: { children: React.ReactNode }) {
  const { data: categories } = useQuery({
    queryKey: ['tagCategories'],
    queryFn: tagApi.getCategories,
    staleTime: 5 * 60 * 1000,
  })

  const colorMap = useMemo(() => {
    const map = new Map<string, string>()
    if (categories) {
      for (const cat of categories) {
        if (cat.color) map.set(cat.name, cat.color)
      }
    }
    return map
  }, [categories])

  return <TagColorContext.Provider value={colorMap}>{children}</TagColorContext.Provider>
}

/** Get the raw map: category name → Tailwind color name */
// eslint-disable-next-line react-refresh/only-export-components -- context hooks intentionally co-exported with provider
export function useCategoryColorMap(): CategoryColorMap {
  return useContext(TagColorContext)
}

/**
 * Returns a function: (categoryName: string) => TagColor
 * Drop-in replacement for the old getTagColor(categoryName) pattern.
 */
// eslint-disable-next-line react-refresh/only-export-components -- context hooks intentionally co-exported with provider
export function useGetTagColor(): (categoryName: string) => TagColor {
  const map = useContext(TagColorContext)
  return useCallback((categoryName: string) => getTagColor(map.get(categoryName) ?? null), [map])
}

/**
 * Build a lookup function from a list of TagCategory objects.
 * Use this in components that already have categories loaded
 * (e.g. FilterMenuContent receives them as props).
 */
// eslint-disable-next-line react-refresh/only-export-components -- utility function intentionally co-exported with provider
export function buildColorLookup(categories: TagCategory[]): (categoryName: string) => TagColor {
  const map = new Map<string, string>()
  for (const cat of categories) {
    if (cat.color) map.set(cat.name, cat.color)
  }
  return (name: string) => getTagColor(map.get(name) ?? null)
}
