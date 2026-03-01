import { Dialog, DialogContent } from '@/components/ui/dialog'

interface FileCardLightboxProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  src: string
  alt: string
  isVideo: boolean
}

export function FileCardLightbox({ open, onOpenChange, src, alt, isVideo }: FileCardLightboxProps) {
  if (!open) return null

  return (
    <Dialog open onOpenChange={onOpenChange}>
      <DialogContent
        className="max-w-none max-h-none w-[95vw] h-[95vh] bg-black/95 border-0 p-4 flex items-center justify-center [&>button]:text-white [&>button]:hover:bg-white/20 cursor-pointer"
        onClick={() => onOpenChange(false)}
      >
        {isVideo ? (
          <video
            src={src}
            controls
            autoPlay
            loop
            className="max-w-full max-h-full object-contain rounded cursor-default"
            onClick={(e) => e.stopPropagation()}
          />
        ) : (
          <img
            src={src}
            alt={alt}
            className="max-w-full max-h-full object-contain rounded cursor-default"
            onClick={(e) => e.stopPropagation()}
          />
        )}
      </DialogContent>
    </Dialog>
  )
}
