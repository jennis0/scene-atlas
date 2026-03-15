import { useState, useEffect } from 'react'
import { modelsApi, type ModelInfo, type SetupStatus } from '@/lib/api/modelsApi'
import { jobApi } from '@/lib/api/jobApi'
import { HARDWARE_BADGE } from '@/lib/modelConstants'

interface ModelSetupScreenProps {
  onComplete: () => void
}

const GPU_PROVIDER_LABELS: Record<string, string> = {
  CUDAExecutionProvider: 'NVIDIA GPU (CUDA)',
  DmlExecutionProvider: 'DirectML GPU',
  CoreMLExecutionProvider: 'Apple GPU (Core ML)',
}


type Phase = 'loading' | 'select' | 'submitting' | 'progress' | 'error'

export function ModelSetupScreen({ onComplete }: ModelSetupScreenProps) {
  const [phase, setPhase] = useState<Phase>('loading')
  const [setupStatus, setSetupStatus] = useState<SetupStatus | null>(null)
  const [models, setModels] = useState<ModelInfo[]>([])
  const [selectedModel, setSelectedModel] = useState<string>('')
  const [jobId, setJobId] = useState<string | null>(null)
  const [progressMessage, setProgressMessage] = useState<string>('Starting…')
  const [jobStatus, setJobStatus] = useState<string>('')
  const [errorMessage, setErrorMessage] = useState<string>('')

  useEffect(() => {
    Promise.all([modelsApi.setupStatus(), modelsApi.list()])
      .then(([status, list]) => {
        setSetupStatus(status)
        setModels(list.models)
        setSelectedModel(status.recommended)
        setPhase('select')
      })
      .catch((err) => {
        setErrorMessage(err?.message ?? 'Failed to load model information.')
        setPhase('error')
      })
  }, [])

  // Poll job when in progress phase
  useEffect(() => {
    if (phase !== 'progress' || !jobId) return

    const interval = setInterval(async () => {
      try {
        const job = await jobApi.get(jobId)
        if (job.progress) setProgressMessage(job.progress)
        setJobStatus(job.status)
        if (job.status === 'completed') {
          clearInterval(interval)
          onComplete()
        } else if (job.status === 'failed') {
          clearInterval(interval)
          setErrorMessage(job.error ?? 'Model activation failed.')
          setPhase('error')
        }
      } catch {
        // transient network error — keep polling
      }
    }, 2000)

    return () => clearInterval(interval)
  }, [phase, jobId, onComplete])

  const handleGetStarted = async () => {
    setPhase('submitting')
    try {
      const result = await modelsApi.setActiveModel(selectedModel)
      if (result.job_id) {
        setJobId(result.job_id)
        setPhase('progress')
      } else {
        // No async job — already done
        onComplete()
      }
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to activate model.'
      setErrorMessage(message)
      setPhase('error')
    }
  }

  if (phase === 'loading') {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center">
        <p className="text-muted-foreground text-sm">Loading model information…</p>
      </div>
    )
  }

  if (phase === 'error') {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center">
        <div className="max-w-md text-center space-y-3">
          <p className="font-semibold text-destructive">Setup Error</p>
          <p className="text-sm text-muted-foreground">{errorMessage}</p>
          <button
            type="button"
            onClick={() => {
              setPhase('loading')
              setErrorMessage('')
              Promise.all([modelsApi.setupStatus(), modelsApi.list()])
                .then(([status, list]) => {
                  setSetupStatus(status)
                  setModels(list.models)
                  setSelectedModel(status.recommended)
                  setPhase('select')
                })
                .catch((err) => {
                  setErrorMessage(err?.message ?? 'Failed to load model information.')
                  setPhase('error')
                })
            }}
            className="px-4 py-2 rounded bg-primary text-primary-foreground text-sm hover:bg-primary/90 transition-colors"
          >
            Retry
          </button>
        </div>
      </div>
    )
  }

  if (phase === 'progress') {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center">
        <div className="max-w-sm text-center space-y-4">
          <p className="font-semibold">Setting up AI model…</p>
          <p className="text-sm text-muted-foreground">{progressMessage}</p>
          {jobStatus && (
            <p className="text-xs text-muted-foreground capitalize">Status: {jobStatus}</p>
          )}
          <div className="w-full h-1.5 bg-muted rounded-full overflow-hidden">
            <div className="h-full bg-primary rounded-full animate-pulse w-2/3" />
          </div>
        </div>
      </div>
    )
  }

  const gpuLabel = setupStatus?.gpu_provider
    ? GPU_PROVIDER_LABELS[setupStatus.gpu_provider] ?? setupStatus.gpu_provider
    : null

  return (
    <div className="min-h-screen bg-background flex items-center justify-center p-6">
      <div className="w-full max-w-2xl space-y-6">
        {/* Header */}
        <div className="text-center space-y-2">
          <h1 className="text-2xl font-bold">Welcome to Scene Atlas</h1>
          <p className="text-muted-foreground text-sm">
            Choose an AI model to enable semantic image search. You can change this later in
            Settings.
          </p>
        </div>

        {/* GPU detection badge */}
        <div className="flex justify-center">
          {gpuLabel ? (
            <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium bg-purple-100 text-purple-700 dark:bg-purple-900/40 dark:text-purple-300">
              <span className="h-1.5 w-1.5 rounded-full bg-purple-500" />
              GPU detected: {gpuLabel}
            </span>
          ) : (
            <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium bg-muted text-muted-foreground">
              <span className="h-1.5 w-1.5 rounded-full bg-muted-foreground" />
              No GPU detected — CPU mode
            </span>
          )}
        </div>

        {/* Model cards */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          {models.map((model) => {
            const isSelected = selectedModel === model.name
            const isRecommended = setupStatus?.recommended === model.name
            const hwBadge = HARDWARE_BADGE[model.recommended_hardware] ?? HARDWARE_BADGE['any']

            return (
              <button
                key={model.name}
                type="button"
                onClick={() => setSelectedModel(model.name)}
                className={`relative text-left rounded-lg border p-4 space-y-2 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 ${
                  isSelected
                    ? 'border-primary bg-primary/5'
                    : 'border-border bg-card hover:border-border/80 hover:bg-accent/30'
                }`}
              >
                {/* Recommended badge */}
                {isRecommended && (
                  <span className="absolute top-2 right-2 text-[10px] font-semibold uppercase tracking-wide px-1.5 py-0.5 rounded bg-primary/10 text-primary">
                    Recommended
                  </span>
                )}

                {/* Label + hardware badge */}
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="font-semibold text-sm">{model.label}</span>
                  <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded ${hwBadge.className}`}>
                    {hwBadge.label}
                  </span>
                </div>

                {/* Description */}
                <p className="text-xs text-muted-foreground leading-relaxed">{model.description}</p>

                {/* Size */}
                <p className="text-xs text-muted-foreground">~{model.approx_size_mb} MB</p>

                {/* Technical details collapsible */}
                <details
                  className="text-xs"
                  onClick={(e) => e.stopPropagation()}
                >
                  <summary className="cursor-pointer text-muted-foreground hover:text-foreground select-none">
                    Technical details
                  </summary>
                  <p className="mt-1 text-muted-foreground leading-relaxed">
                    {model.description_technical}
                  </p>
                </details>
              </button>
            )
          })}
        </div>

        {/* Get Started button */}
        <div className="flex justify-center">
          <button
            type="button"
            onClick={handleGetStarted}
            disabled={!selectedModel || phase === 'submitting'}
            className="px-6 py-2.5 rounded-lg bg-primary text-primary-foreground font-medium text-sm hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {phase === 'submitting' ? 'Starting…' : 'Get Started'}
          </button>
        </div>
      </div>
    </div>
  )
}
