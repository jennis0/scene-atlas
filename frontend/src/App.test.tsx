import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { modelsApi, type SetupStatus } from './lib/api/modelsApi'
import App from './App'

vi.mock('./lib/api/modelsApi', () => ({ modelsApi: { setupStatus: vi.fn() } }))
vi.mock('./components/setup/SetupWizard', () => ({
  SetupWizard: ({ status }: { status: SetupStatus }) => (
    <div>setup wizard{status.setup_completed ? ' (model only)' : ''}</div>
  ),
}))
vi.mock('./pages/Gallery', () => ({ Gallery: () => <div>gallery</div> }))
vi.mock('./contexts/ThemeContext', () => ({ useTheme: () => ({ theme: 'dark' }) }))

const setupStatus = vi.mocked(modelsApi.setupStatus)

function status(overrides: Partial<SetupStatus>): SetupStatus {
  return {
    needs_model: false,
    setup_completed: true,
    model_activating: false,
    recommended: 'small',
    has_gpu: false,
    gpu_provider: null,
    ...overrides,
  }
}

describe('App first-run gate', () => {
  beforeEach(() => {
    setupStatus.mockReset()
  })
  afterEach(() => {
    delete (window as { electronAPI?: unknown }).electronAPI
  })

  it.each([
    ['a new library', { setup_completed: false, needs_model: true }, 'setup wizard'],
    ['a new library whose model is preset', { setup_completed: false }, 'setup wizard'],
    ['a set-up library missing its model', { needs_model: true }, 'setup wizard (model only)'],
    [
      'a set-up library whose model is downloading',
      { needs_model: true, model_activating: true },
      'gallery',
    ],
    ['a set-up library', {}, 'gallery'],
  ])('%s shows the %s', async (_case, overrides, expected) => {
    setupStatus.mockResolvedValue(status(overrides))
    render(<App />)
    expect(await screen.findByText(expected)).toBeInTheDocument()
  })

  it.each([
    ['server', undefined, /Check that it is running/],
    ['desktop app', {}, /restart Scene Atlas/],
  ])('says how to recover in the %s when the backend is unreachable', async (_m, api, text) => {
    ;(window as { electronAPI?: unknown }).electronAPI = api
    setupStatus.mockRejectedValue(new Error('offline'))
    render(<App />)
    expect(await screen.findByRole('alert')).toHaveTextContent(text)
  })

  it('tries again', async () => {
    setupStatus.mockRejectedValueOnce(new Error('offline')).mockResolvedValue(status({}))
    render(<App />)
    await userEvent.click(await screen.findByRole('button', { name: 'Try again' }))
    expect(await screen.findByText('gallery')).toBeInTheDocument()
  })
})
