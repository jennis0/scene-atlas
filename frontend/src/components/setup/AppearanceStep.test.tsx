import { afterEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { AppUpdateState } from '@/electron'
import { ThemeProvider } from '@/contexts/ThemeContext'
import { AppearanceStep } from './AppearanceStep'

const NAV = { steps: ['appearance', 'format'] as const, index: 0, onNext: vi.fn() }

/** The desktop app's updater before the user has chosen how it updates. */
function desktopUpdater(): { setUpdateChoice: ReturnType<typeof vi.fn> } {
  const state: AppUpdateState = {
    status: 'idle',
    mode: 'install',
    currentVersion: '0.2.0',
    choice: 'ask',
    choiceMade: false,
  }
  const api = {
    getUpdateState: vi.fn().mockResolvedValue(state),
    onUpdateState: vi.fn(() => () => {}),
    setUpdateChoice: vi.fn((choice: string) =>
      Promise.resolve({ ...state, choice, choiceMade: true }),
    ),
  }
  ;(window as { electronAPI?: unknown }).electronAPI = api
  return api
}

function renderStep() {
  render(
    <ThemeProvider>
      <AppearanceStep nav={NAV} />
    </ThemeProvider>,
  )
}

afterEach(() => {
  delete (window as { electronAPI?: unknown }).electronAPI
})

describe('AppearanceStep', () => {
  it('asks how the desktop app updates, starting on Ask first', async () => {
    const api = desktopUpdater()
    renderStep()
    const group = await screen.findByRole('radiogroup', { name: 'New versions' })
    expect(within(group).getByRole('radio', { name: 'Ask first' })).toBeChecked()
    // Shown isn't chosen: the app doesn't check until the user picks or finishes setup.
    expect(api.setUpdateChoice).not.toHaveBeenCalled()

    await userEvent.click(within(group).getByRole('radio', { name: 'Automatic' }))
    expect(api.setUpdateChoice).toHaveBeenCalledWith('automatic')
  })

  it('has no update choice on a server', async () => {
    renderStep()
    await waitFor(() => expect(screen.getByText('Welcome to Scene Atlas')).toBeInTheDocument())
    expect(screen.queryByRole('radiogroup', { name: 'New versions' })).not.toBeInTheDocument()
  })
})
