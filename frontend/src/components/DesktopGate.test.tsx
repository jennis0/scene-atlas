import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, act, waitFor } from '@testing-library/react'
import { DesktopGate } from './DesktopGate'

describe('DesktopGate', () => {
  afterEach(() => {
    delete (window as any).electronAPI
    delete window.__SCENE_ATLAS_PORT__
  })

  it('renders children immediately in server mode (no electronAPI)', () => {
    delete (window as any).electronAPI

    render(
      <DesktopGate>
        <div data-testid="app-content">Hello</div>
      </DesktopGate>,
    )

    expect(screen.getByTestId('app-content')).toBeInTheDocument()
  })

  it('shows loading screen when electronAPI is present (app mode)', () => {
    ;(window as any).electronAPI = {
      onBackendReady: vi.fn(),
      onBackendError: vi.fn(),
    }

    render(
      <DesktopGate>
        <div data-testid="app-content">Hello</div>
      </DesktopGate>,
    )

    // App content should not be visible while waiting
    expect(screen.queryByTestId('app-content')).not.toBeInTheDocument()
    // Loading screen should be visible
    expect(screen.getByText('Scene Atlas')).toBeInTheDocument()
  })

  it('shows children after backend-ready signal and health check passes', async () => {
    let readyCallback: ((port: number) => void) | null = null

    ;(window as any).electronAPI = {
      onBackendReady: (cb: (port: number) => void) => {
        readyCallback = cb
      },
      onBackendError: vi.fn(),
    }

    // Mock fetch for health polling
    const mockFetch = vi.fn().mockResolvedValue({ ok: true })
    vi.stubGlobal('fetch', mockFetch)

    render(
      <DesktopGate>
        <div data-testid="app-content">Hello</div>
      </DesktopGate>,
    )

    // Should be in waiting state
    expect(screen.queryByTestId('app-content')).not.toBeInTheDocument()

    // Simulate backend ready signal — use async act() to flush the setTimeout
    // poll chain and its resulting state updates (setState calls inside the
    // async poll function).
    await act(async () => readyCallback!(8000))

    // Wait for health poll to succeed and children to appear
    await waitFor(
      () => {
        expect(screen.getByTestId('app-content')).toBeInTheDocument()
      },
      { timeout: 5000 },
    )

    vi.unstubAllGlobals()
  })

  it('shows error state when backend-error signal fires', async () => {
    let errorCallback: ((message: string) => void) | null = null

    ;(window as any).electronAPI = {
      onBackendReady: vi.fn(),
      onBackendError: (cb: (message: string) => void) => {
        errorCallback = cb
      },
    }

    render(
      <DesktopGate>
        <div data-testid="app-content">Hello</div>
      </DesktopGate>,
    )

    // Simulate backend error
    act(() => errorCallback!('Sidecar crashed with exit code 1'))

    await vi.waitFor(() => {
      expect(screen.getByText(/couldn.*t start/i)).toBeInTheDocument()
    })

    // Children should still not be visible
    expect(screen.queryByTestId('app-content')).not.toBeInTheDocument()
  })
})
