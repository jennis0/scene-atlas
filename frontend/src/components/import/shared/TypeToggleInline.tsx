import type { EditableFileState } from '@/types'

interface TypeToggleInlineProps {
  imageType: EditableFileState['image_type']
  disabled?: boolean
  onUpdate: (imageType: 'battlemap' | 'scene') => void
}

export function TypeToggleInline({ imageType, disabled, onUpdate }: TypeToggleInlineProps) {
  if (disabled) {
    return (
      <span className="text-[10px] text-muted-foreground capitalize">
        {imageType === 'scene' ? 'Scene' : 'Map'}
      </span>
    )
  }

  return (
    <div className="inline-flex rounded-md overflow-hidden border border-border">
      <button
        type="button"
        aria-pressed={imageType !== 'scene'}
        onClick={() => onUpdate('battlemap')}
        className={`px-1.5 py-0.5 text-[10px] font-medium transition-colors ${
          imageType !== 'scene'
            ? 'bg-primary/10 text-primary'
            : 'text-muted-foreground hover:text-muted-foreground'
        }`}
      >
        Map
      </button>
      <button
        type="button"
        aria-pressed={imageType === 'scene'}
        onClick={() => onUpdate('scene')}
        className={`px-1.5 py-0.5 text-[10px] font-medium border-l border-border transition-colors ${
          imageType === 'scene'
            ? 'bg-primary/10 text-primary'
            : 'text-muted-foreground hover:text-muted-foreground'
        }`}
      >
        Scene
      </button>
    </div>
  )
}
