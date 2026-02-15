import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { searchApi, tagApi } from '@/lib/api'
import { ImageGrid } from '@/components/ImageGrid'
import { ImageViewer } from '@/components/ImageViewer'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import type { Image } from '@/types'

export function Search() {
  const [selectedImage, setSelectedImage] = useState<{ image: Image; index: number } | null>(null)
  const [semanticQuery, setSemanticQuery] = useState('')
  const [isSearching, setIsSearching] = useState(false)
  const [results, setResults] = useState<Image[]>([])

  const { data: tagCategories = [] } = useQuery({
    queryKey: ['tagCategories'],
    queryFn: () => tagApi.getCategories(),
  })

  const handleSemanticSearch = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!semanticQuery.trim()) return

    setIsSearching(true)
    try {
      const response = await searchApi.semantic(semanticQuery, 50)
      if (response.error) {
        console.error('Semantic search error:', response.error)
        setResults([])
      } else {
        setResults(response.results.map((r) => r.image))
      }
    } catch (error) {
      console.error('Search failed:', error)
      setResults([])
    } finally {
      setIsSearching(false)
    }
  }

  const handleNext = () => {
    if (!selectedImage || selectedImage.index >= results.length - 1) return
    const nextIndex = selectedImage.index + 1
    setSelectedImage({ image: results[nextIndex], index: nextIndex })
  }

  const handlePrevious = () => {
    if (!selectedImage || selectedImage.index <= 0) return
    const prevIndex = selectedImage.index - 1
    setSelectedImage({ image: results[prevIndex], index: prevIndex })
  }

  return (
    <div className="flex h-screen flex-col">
      {/* Header */}
      <header className="border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
        <div className="container mx-auto px-4 py-4">
          <h1 className="text-3xl font-bold mb-4">Semantic Search</h1>

          <form onSubmit={handleSemanticSearch} className="flex gap-2">
            <Input
              type="text"
              placeholder="Describe the scene you're looking for..."
              value={semanticQuery}
              onChange={(e) => setSemanticQuery(e.target.value)}
              className="flex-1"
            />
            <Button type="submit" disabled={isSearching}>
              {isSearching ? 'Searching...' : 'Search'}
            </Button>
          </form>

          {/* Tag categories for reference */}
          {tagCategories.length > 0 && (
            <div className="mt-4">
              <p className="text-sm text-muted-foreground mb-2">
                Available tag categories:
              </p>
              <div className="flex flex-wrap gap-1">
                {tagCategories.map((category) => (
                  <Badge key={category.id} variant="outline">
                    {category.name}
                  </Badge>
                ))}
              </div>
            </div>
          )}
        </div>
      </header>

      {/* Main content */}
      <main className="flex-1 overflow-hidden">
        {results.length === 0 ? (
          <div className="flex h-full items-center justify-center">
            <div className="text-center max-w-md">
              <p className="text-muted-foreground mb-2">
                {isSearching
                  ? 'Searching...'
                  : 'Enter a description to find similar images'}
              </p>
              <p className="text-sm text-muted-foreground">
                Try: "abandoned mine with crystals" or "winter forest temple"
              </p>
            </div>
          </div>
        ) : (
          <ImageGrid
            images={results}
            onImageClick={(image, index) => setSelectedImage({ image, index })}
          />
        )}
      </main>

      {/* Image viewer modal */}
      {selectedImage && (
        <ImageViewer
          image={selectedImage.image}
          onClose={() => setSelectedImage(null)}
          onNext={selectedImage.index < results.length - 1 ? handleNext : undefined}
          onPrevious={selectedImage.index > 0 ? handlePrevious : undefined}
        />
      )}
    </div>
  )
}
