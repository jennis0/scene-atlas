import type { ModelInfo } from '@/lib/api/modelsApi'

/** Five dots, filled to `value`: filled vs hollow carries the meaning, not colour. */
function Dots({ label, value }: { label: string; value: number }) {
  return (
    <>
      <dt className="text-2xs text-muted-foreground">{label}</dt>
      <dd
        className="flex items-center gap-[3px]"
        role="img"
        aria-label={`${label}: ${value} out of 5`}
      >
        {[1, 2, 3, 4, 5].map((i) => (
          <span
            key={i}
            className={`h-2 w-2 rounded-full border border-foreground/70 ${i <= value ? 'bg-foreground/80' : ''}`}
          />
        ))}
      </dd>
    </>
  )
}

/** Indicative speed (on this computer: with or without a GPU) and search quality. */
export function ModelRatings({ model, hasGpu }: { model: ModelInfo; hasGpu: boolean }) {
  // Decoration only: an older backend without ratings shouldn't break the picker
  if (!model.speed || !model.search_quality) return null
  return (
    <dl className="grid grid-cols-[auto_1fr] items-center gap-x-3 gap-y-1">
      <Dots label="Speed" value={hasGpu ? model.speed.gpu : model.speed.cpu} />
      <Dots label="Search" value={model.search_quality} />
    </dl>
  )
}
