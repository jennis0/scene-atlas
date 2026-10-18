import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { modelsApi, type ModelInfo } from '@/lib/api/modelsApi'
import { ModelSetupScreen } from './ModelSetupScreen'

vi.mock('@/lib/api/modelsApi', () => ({
  modelsApi: {
    setupStatus: vi.fn(),
    list: vi.fn(),
    setActiveModel: vi.fn(),
    setupComplete: vi.fn(),
  },
}))
vi.mock('@/lib/api/jobApi', () => ({ jobApi: { get: vi.fn() } }))
vi.mock('@/lib/api/tagApi', () => ({
  tagApi: { getTagPacks: vi.fn().mockResolvedValue([]), importMultipleTagPacks: vi.fn() },
}))

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

describe('ModelSetupScreen', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(modelsApi.setupStatus).mockResolvedValue({
      needs_model: true,
      needs_tag_packs: true,
      recommended: 'medium',
      has_gpu: false,
      gpu_provider: null,
    })
    vi.mocked(modelsApi.list).mockResolvedValue({
      models: [model('small', 'Fast'), model('medium', 'Balanced'), model('large', 'Best')],
    })
    vi.mocked(modelsApi.setActiveModel).mockResolvedValue({ job_id: null } as never)
  })

  it('offers the models as a radio group with the recommended one selected', async () => {
    render(<ModelSetupScreen onComplete={vi.fn()} />)
    const group = await screen.findByRole('radiogroup', { name: 'Search model' })
    const radios = within(group).getAllByRole('radio')
    expect(radios).toHaveLength(3)
    const balanced = within(group).getByRole('radio', { name: 'Balanced' })
    expect(balanced).toBeChecked()
    expect(balanced).toHaveAccessibleDescription(/^Recommended for this computer\./)
    expect(within(group).getByRole('radio', { name: 'Fast' })).toHaveAccessibleDescription(
      /Fast description/,
    )
  })

  it('selects a model by keyboard, mouse on the card, or its label', async () => {
    const user = userEvent.setup()
    render(<ModelSetupScreen onComplete={vi.fn()} />)
    const best = await screen.findByRole('radio', { name: 'Best' })

    await user.click(screen.getByText('Fast description'))
    expect(screen.getByRole('radio', { name: 'Fast' })).toBeChecked()

    best.focus()
    await user.keyboard(' ')
    expect(best).toBeChecked()
  })

  it('keeps technical details out of any button and does not select the card', async () => {
    const user = userEvent.setup()
    render(<ModelSetupScreen onComplete={vi.fn()} />)
    await screen.findByRole('radiogroup')

    const summaries = screen.getAllByText('Technical details')
    for (const summary of summaries) expect(summary.closest('button')).toBeNull()

    await user.click(summaries[0])
    expect(screen.getByRole('radio', { name: 'Balanced' })).toBeChecked()
  })

  it('activates the chosen model', async () => {
    const user = userEvent.setup()
    render(<ModelSetupScreen onComplete={vi.fn()} />)
    await user.click(await screen.findByRole('radio', { name: 'Best' }))
    await user.click(screen.getByRole('button', { name: 'Get Started' }))
    expect(modelsApi.setActiveModel).toHaveBeenCalledWith('large')
  })
})
