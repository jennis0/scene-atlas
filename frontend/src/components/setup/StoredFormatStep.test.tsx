import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { settingsApi } from '@/lib/api/settingsApi'
import type { AppSettings } from '@/types'
import { StoredFormatStep } from './StoredFormatStep'

vi.mock('@/lib/api/settingsApi', () => ({ settingsApi: { get: vi.fn(), patch: vi.fn() } }))

const get = vi.mocked(settingsApi.get)
const patch = vi.mocked(settingsApi.patch)

function settings(stored_format: AppSettings['stored_format']): AppSettings {
  return { stored_format } as AppSettings
}

function renderStep(onNext = vi.fn()) {
  render(<StoredFormatStep nav={{ steps: ['format', 'model'], index: 0, onNext }} />)
  return onNext
}

describe('StoredFormatStep', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    patch.mockResolvedValue(settings('webp'))
  })

  it('starts from the current setting (a server may preset WebP)', async () => {
    get.mockResolvedValue(settings('webp'))
    renderStep()
    expect(await screen.findByRole('radio', { name: 'Convert to WebP' })).toBeChecked()
  })

  it('saves a changed choice, then moves on', async () => {
    get.mockResolvedValue(settings('original'))
    const user = userEvent.setup()
    const onNext = renderStep()
    await user.click(await screen.findByRole('radio', { name: 'Convert to WebP' }))
    await user.click(screen.getByRole('button', { name: 'Continue' }))
    expect(patch).toHaveBeenCalledWith({ stored_format: 'webp' })
    expect(onNext).toHaveBeenCalled()
  })

  it('does not write the setting when it is unchanged', async () => {
    get.mockResolvedValue(settings('original'))
    const user = userEvent.setup()
    const onNext = renderStep()
    await screen.findByRole('radio', { name: 'Keep files as they are', checked: true })
    await user.click(screen.getByRole('button', { name: 'Continue' }))
    expect(patch).not.toHaveBeenCalled()
    expect(onNext).toHaveBeenCalled()
  })

  it('stays on the step when saving fails', async () => {
    get.mockResolvedValue(settings('original'))
    patch.mockRejectedValue(new Error('Server error'))
    const user = userEvent.setup()
    const onNext = renderStep()
    await user.click(await screen.findByRole('radio', { name: 'Convert to WebP' }))
    await user.click(screen.getByRole('button', { name: 'Continue' }))
    expect(await screen.findByRole('alert')).toBeInTheDocument()
    expect(onNext).not.toHaveBeenCalled()
  })
})
