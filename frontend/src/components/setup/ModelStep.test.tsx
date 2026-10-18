import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { modelsApi, type ModelInfo, type SetupStatus } from '@/lib/api/modelsApi'
import { ModelStep } from './ModelStep'

vi.mock('@/lib/api/modelsApi', () => ({
  modelsApi: { list: vi.fn(), setActiveModel: vi.fn() },
}))

const STATUS: SetupStatus = {
  needs_model: true,
  setup_completed: false,
  model_activating: false,
  recommended: 'medium',
  has_gpu: false,
  gpu_provider: null,
}

function model(name: string, label: string): ModelInfo {
  return {
    name,
    label,
    description: `${label} description`,
    description_technical: `${label} internals`,
    recommended_hardware: 'any',
    approx_size_mb: 100,
    speed: { cpu: 3, gpu: 5 },
    search_quality: 3,
    downloaded: false,
    version_info: null,
    active: false,
  }
}

function renderStep(onNext = vi.fn()) {
  render(<ModelStep nav={{ steps: ['tag-packs', 'model'], index: 1, onNext }} status={STATUS} />)
  return onNext
}

describe('ModelStep', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(modelsApi.list).mockResolvedValue({
      models: [model('small', 'Small'), model('medium', 'Medium'), model('large', 'Large')],
    })
    vi.mocked(modelsApi.setActiveModel).mockResolvedValue({ status: 'started', job_id: 'j1' })
  })

  it('offers the models as a radio group with the recommended one selected', async () => {
    renderStep()
    const group = await screen.findByRole('radiogroup', { name: 'Search model' })
    expect(within(group).getAllByRole('radio')).toHaveLength(3)
    const medium = within(group).getByRole('radio', { name: 'Medium' })
    expect(medium).toBeChecked()
    expect(medium).toHaveAccessibleDescription(/Recommended\.$/)
    expect(within(group).getByRole('radio', { name: 'Small' })).toHaveAccessibleDescription(
      /Small description/,
    )
  })

  it('selects a model by clicking the card or by keyboard', async () => {
    const user = userEvent.setup()
    renderStep()
    const large = await screen.findByRole('radio', { name: 'Large' })

    await user.click(screen.getByText('Small description'))
    expect(screen.getByRole('radio', { name: 'Small' })).toBeChecked()

    large.focus()
    await user.keyboard(' ')
    expect(large).toBeChecked()
  })

  it('keeps technical details out of any button and does not select the card', async () => {
    const user = userEvent.setup()
    renderStep()
    await screen.findByRole('radiogroup')

    const summaries = screen.getAllByText('Technical details')
    for (const summary of summaries) expect(summary.closest('button')).toBeNull()

    await user.click(summaries[0])
    expect(screen.getByRole('radio', { name: 'Medium' })).toBeChecked()
  })

  it('Finish starts the chosen model and ends setup without waiting for the download', async () => {
    const user = userEvent.setup()
    const onNext = renderStep()
    await user.click(await screen.findByRole('radio', { name: 'Large' }))
    await user.click(screen.getByRole('button', { name: 'Finish' }))
    expect(modelsApi.setActiveModel).toHaveBeenCalledWith('large')
    expect(onNext).toHaveBeenCalled()
  })

  it('stays on the step with an explanation when the model cannot be started', async () => {
    vi.mocked(modelsApi.setActiveModel).mockRejectedValue(new Error('Not enough disk space'))
    const user = userEvent.setup()
    const onNext = renderStep()
    await user.click(await screen.findByRole('button', { name: 'Finish' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Not enough disk space')
    expect(onNext).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: 'Finish' })).toBeEnabled()
  })
})
