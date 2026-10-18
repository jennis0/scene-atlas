import { useEffect, useState } from 'react'
import { modelsApi, type ModelInfo, type SetupStatus } from '@/lib/api/modelsApi'
import { getApiErrorMessage } from '@/lib/getErrorMessage'
import { GpuStatus } from '@/components/models/GpuStatus'
import { ModelRatings } from '@/components/models/ModelRatings'
import { AboutModelsLink } from '@/components/models/AboutModelsLink'
import { ChoiceCard } from './ChoiceCard'
import { LoadFailed } from './LoadFailed'
import { SetupFrame } from './SetupFrame'
import type { StepNav } from './steps'

interface ModelStepProps {
  nav: StepNav
  status: SetupStatus
}

/** The search model, chosen last: Finish starts its download in the background and setup
 * ends at once; the gallery waits for the model (design/first-run.md). */
export function ModelStep({ nav, status }: ModelStepProps) {
  const [models, setModels] = useState<ModelInfo[] | null>(null)
  const [selected, setSelected] = useState(status.recommended)
  const [loadFailed, setLoadFailed] = useState(false)
  const [starting, setStarting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const loadModels = () => {
    setLoadFailed(false)
    modelsApi
      .list()
      .then((list) => setModels(list.models))
      .catch(() => setLoadFailed(true))
  }

  useEffect(() => {
    loadModels()
  }, [])

  const handleFinish = async () => {
    setStarting(true)
    setError(null)
    try {
      await modelsApi.setActiveModel(selected)
      nav.onNext()
    } catch (err) {
      setError(getApiErrorMessage(err, 'Could not start the model download.'))
      setStarting(false)
    }
  }

  return (
    <SetupFrame
      nav={nav}
      title="Choose a search model"
      description="The model lets you find maps by describing them, like “a snowy forest road at night”. Finish starts the download; you can start importing as soon as it's ready. You can switch models later in Settings."
      primary={{ onClick: handleFinish, busy: starting, disabled: !models }}
      error={error}
    >
      <GpuStatus hasGpu={status.has_gpu} provider={status.gpu_provider} />

      {loadFailed && (
        <LoadFailed message="Couldn't load the list of models." onRetry={loadModels} />
      )}

      {models && (
        <ModelChoices models={models} status={status} selected={selected} onSelect={setSelected} />
      )}

      <AboutModelsLink />
    </SetupFrame>
  )
}

interface ModelChoicesProps {
  models: ModelInfo[]
  status: SetupStatus
  selected: string
  onSelect: (name: string) => void
}

function ModelChoices({ models, status, selected, onSelect }: ModelChoicesProps) {
  return (
    <div
      role="radiogroup"
      aria-label="Search model"
      className="grid grid-cols-1 sm:grid-cols-3 gap-3"
    >
      {models.map((model) => (
        <ChoiceCard
          key={model.name}
          name="setup-model"
          checked={selected === model.name}
          onSelect={() => onSelect(model.name)}
          choice={{
            value: model.name,
            label: model.label,
            badge: status.recommended === model.name ? 'Recommended' : undefined,
            description: (
              <>
                <p>{model.description}</p>
                <ModelRatings model={model} hasGpu={status.has_gpu} />
                <p className="text-2xs">{model.approx_size_mb} MB download</p>
              </>
            ),
            footer: (
              <details className="text-xs" onClick={(e) => e.stopPropagation()}>
                <summary className="cursor-pointer text-muted-foreground hover:text-foreground select-none">
                  Technical details
                </summary>
                <p className="mt-1 text-muted-foreground leading-relaxed">
                  {model.description_technical}
                </p>
              </details>
            ),
          }}
        />
      ))}
    </div>
  )
}
