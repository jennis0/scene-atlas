import { render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('./lib/api/modelsApi', () => ({
  modelsApi: {
    setupStatus: vi.fn().mockResolvedValue({
      needs_model: true,
      needs_tag_packs: true,
      recommended: 'small',
      has_gpu: false,
      gpu_provider: null,
    }),
  },
}))
vi.mock('./components/setup/ModelSetupScreen', () => ({
  ModelSetupScreen: () => <div>model setup</div>,
}))
vi.mock('./pages/Gallery', () => ({ Gallery: () => <div>gallery</div> }))
vi.mock('./contexts/ThemeContext', () => ({ useTheme: () => ({ theme: 'dark' }) }))

describe('App first-run setup', () => {
  afterEach(() => {
    vi.resetModules()
    delete (window as { electronAPI?: unknown }).electronAPI
  })

  it.each([
    ['server', undefined],
    ['desktop', { platform: 'win32' }],
  ])('shows the setup screen in %s mode when no model is installed', async (_mode, api) => {
    ;(window as { electronAPI?: unknown }).electronAPI = api
    const { default: App } = await import('./App')
    render(<App />)
    expect(await screen.findByText('model setup')).toBeTruthy()
  })
})
