import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ThemeProvider } from '@/contexts/ThemeContext'
import { modelsApi, type SetupStatus } from '@/lib/api/modelsApi'
import { settingsApi } from '@/lib/api/settingsApi'
import { tagApi } from '@/lib/api/tagApi'
import type { AppSettings } from '@/types'
import { SetupWizard } from './SetupWizard'
import { setupSteps } from './steps'

vi.mock('@/lib/api/modelsApi', () => ({
  modelsApi: { list: vi.fn(), setActiveModel: vi.fn(), setupComplete: vi.fn() },
}))
vi.mock('@/lib/api/settingsApi', () => ({ settingsApi: { get: vi.fn(), patch: vi.fn() } }))
vi.mock('@/lib/api/tagApi', () => ({
  tagApi: { getTagPacks: vi.fn(), importMultipleTagPacks: vi.fn() },
}))

const NEW_LIBRARY: SetupStatus = {
  needs_model: true,
  setup_completed: false,
  model_activating: false,
  recommended: 'small',
  has_gpu: false,
  gpu_provider: null,
}

function renderWizard(status: SetupStatus, onComplete = vi.fn()) {
  render(
    <ThemeProvider>
      <SetupWizard status={status} onComplete={onComplete} />
    </ThemeProvider>,
  )
  return onComplete
}

describe('setupSteps', () => {
  it('runs every step for a new library, ending with the model', () => {
    expect(setupSteps(NEW_LIBRARY)).toEqual(['appearance', 'format', 'tag-packs', 'model'])
  })

  it('skips the model when one is already set up (e.g. EMBEDDING_MODEL)', () => {
    expect(setupSteps({ ...NEW_LIBRARY, needs_model: false })).toEqual([
      'appearance',
      'format',
      'tag-packs',
    ])
  })

  it('asks only for the model once setup is done', () => {
    expect(setupSteps({ ...NEW_LIBRARY, setup_completed: true })).toEqual(['model'])
  })
})

describe('SetupWizard', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    vi.mocked(settingsApi.get).mockResolvedValue({ stored_format: 'original' } as AppSettings)
    vi.mocked(tagApi.getTagPacks).mockResolvedValue([])
    vi.mocked(modelsApi.list).mockResolvedValue({ models: [] })
    vi.mocked(modelsApi.setActiveModel).mockResolvedValue({ status: 'started', job_id: 'j1' })
    vi.mocked(modelsApi.setupComplete).mockResolvedValue(undefined as never)
  })

  it('walks through every step, with Back, and finishes setup', async () => {
    const user = userEvent.setup()
    const onComplete = renderWizard(NEW_LIBRARY)

    const steps = screen.getByRole('list', { name: 'Setup steps' })
    expect(
      within(steps)
        .getAllByRole('listitem')
        .map((li) => li.textContent),
    ).toEqual(['1Appearance', '2Stored format', '3Tag packs', '4Search model'])
    expect(screen.getByRole('heading', { level: 1 })).toHaveFocus()
    expect(screen.queryByRole('button', { name: 'Back' })).not.toBeInTheDocument()

    // Appearance applies at once
    await user.click(screen.getByRole('radio', { name: 'Light' }))
    expect(localStorage.getItem('scene-atlas-theme')).toBe('light')
    await user.click(screen.getByRole('button', { name: 'Continue' }))

    await screen.findByRole('heading', { name: /How should imported images be stored/ })
    await user.click(screen.getByRole('button', { name: 'Back' }))
    expect(await screen.findByRole('heading', { name: /Welcome/ })).toHaveFocus()
    await user.click(screen.getByRole('button', { name: 'Continue' }))

    await screen.findByRole('radio', { name: 'Keep files as they are', checked: true })
    await user.click(screen.getByRole('button', { name: 'Continue' }))

    await screen.findByRole('heading', { name: 'Add tag packs' })
    await waitFor(() => expect(screen.getByRole('button', { name: 'Continue' })).toBeEnabled())
    await user.click(screen.getByRole('button', { name: 'Continue' }))

    await screen.findByRole('heading', { name: 'Choose a search model' })
    expect(screen.getByRole('listitem', { current: 'step' })).toHaveTextContent('Search model')
    await waitFor(() => expect(screen.getByRole('button', { name: 'Finish' })).toBeEnabled())
    await user.click(screen.getByRole('button', { name: 'Finish' }))

    expect(modelsApi.setActiveModel).toHaveBeenCalledWith('small')
    await waitFor(() => expect(onComplete).toHaveBeenCalled())
    expect(modelsApi.setupComplete).toHaveBeenCalled()
  })

  it('finishes on the tag-pack step when the model is already set up', async () => {
    const user = userEvent.setup()
    const onComplete = renderWizard({ ...NEW_LIBRARY, needs_model: false })
    await user.click(screen.getByRole('button', { name: 'Continue' }))
    await screen.findByRole('radio', { name: 'Keep files as they are', checked: true })
    await user.click(screen.getByRole('button', { name: 'Continue' }))
    await screen.findByRole('heading', { name: 'Add tag packs' })
    await waitFor(() => expect(screen.getByRole('button', { name: 'Finish' })).toBeEnabled())
    await user.click(screen.getByRole('button', { name: 'Finish' }))
    await waitFor(() => expect(onComplete).toHaveBeenCalled())
    expect(modelsApi.setActiveModel).not.toHaveBeenCalled()
  })

  it('shows only the model step, without a step list, when just the model is missing', async () => {
    renderWizard({ ...NEW_LIBRARY, setup_completed: true })
    expect(await screen.findByRole('heading', { name: 'Choose a search model' })).toBeVisible()
    expect(screen.queryByRole('list', { name: 'Setup steps' })).not.toBeInTheDocument()
  })
})
