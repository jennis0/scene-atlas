import { createContext, useContext, useMemo, useCallback } from 'react'
import { useQuery } from '@tanstack/react-query'
import { tagApi } from '@/lib/api'
import { QUERY_KEYS } from '@/lib/queryKeys'
import { useTheme } from '@/contexts/ThemeContext'
import { useHighContrast } from '@/lib/contrast'
import { getTagColor } from '@/components/import/tagColors'
import type { TagColor } from '@/components/import/tagColors'

type CategoryColorMap = Map<string, string>

const TagColorContext = createContext<CategoryColorMap>(new Map())

export function TagColorProvider({ children }: { children: React.ReactNode }) {
  const { data: categories } = useQuery({
    queryKey: QUERY_KEYS.tagCategories,
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

/**
 * Returns a function: (categoryName: string | null | undefined) => TagColor
 * Automatically selects the variant for the current theme and contrast.
 * Accepts null/undefined for fallback to default tag color.
 */
// eslint-disable-next-line react-refresh/only-export-components -- context hooks intentionally co-exported with provider
export function useGetTagColor(): (categoryName: string | null | undefined) => TagColor {
  const map = useContext(TagColorContext)
  const { theme } = useTheme()
  const highContrast = useHighContrast()
  return useCallback(
    (categoryName: string | null | undefined) =>
      getTagColor(categoryName ? (map.get(categoryName) ?? null) : null, theme, highContrast),
    [map, theme, highContrast],
  )
}

/** Colours for a tag-palette hue directly (e.g. 'blue'), for badges that aren't tags. */
// eslint-disable-next-line react-refresh/only-export-components -- context hooks intentionally co-exported with provider
export function useHueColor(): (hue: string) => TagColor {
  const { theme } = useTheme()
  const highContrast = useHighContrast()
  return useCallback((hue: string) => getTagColor(hue, theme, highContrast), [theme, highContrast])
}
