import { Cpu, Zap } from 'lucide-react'
import { GPU_PROVIDER_LABELS } from '@/lib/modelConstants'

interface GpuStatusProps {
  hasGpu: boolean
  provider: string | null
}

/** Whether a GPU the models can use was found, and what that means for the choice. */
export function GpuStatus({ hasGpu, provider }: GpuStatusProps) {
  const Icon = hasGpu ? Zap : Cpu
  const name = provider ? (GPU_PROVIDER_LABELS[provider] ?? provider) : null
  return (
    <div className="flex items-start gap-2 rounded-md border border-border bg-secondary/40 px-3 py-2 text-xs">
      <Icon
        aria-hidden="true"
        className={`h-3.5 w-3.5 mt-px shrink-0 ${hasGpu ? 'text-success' : 'text-muted-foreground'}`}
      />
      <p>
        <span className="font-medium text-foreground">
          {hasGpu ? `GPU found${name ? `: ${name}` : ''}.` : 'No compatible GPU found.'}
        </span>{' '}
        <span className="text-muted-foreground">
          {hasGpu
            ? 'Medium and Large will run quickly.'
            : 'Models run on the processor, where Small is quickest.'}
        </span>
      </p>
    </div>
  )
}
