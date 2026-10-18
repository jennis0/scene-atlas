import { describe, it, expect, beforeEach, vi } from 'vitest'
import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ThemeProvider, useTheme } from './ThemeContext'

const STORAGE_KEY = 'scene-atlas-theme'

function TestConsumer() {
  const { theme, themePreference, setThemePreference, toggleTheme } = useTheme()
  return (
    <div>
      <span data-testid="theme">{theme}</span>
      <span data-testid="preference">{themePreference}</span>
      <button onClick={toggleTheme}>Toggle</button>
      <button onClick={() => setThemePreference('system')}>System</button>
    </div>
  )
}

/** A controllable prefers-color-scheme: dark query; jsdom has no matchMedia. */
function mockSystemTheme(dark: boolean) {
  const listeners = new Set<() => void>()
  const query = {
    matches: dark,
    addEventListener: (_: string, fn: () => void) => listeners.add(fn),
    removeEventListener: (_: string, fn: () => void) => listeners.delete(fn),
  }
  vi.stubGlobal('matchMedia', () => query)
  return {
    set(nextDark: boolean) {
      query.matches = nextDark
      act(() => listeners.forEach((fn) => fn()))
    },
  }
}

function renderConsumer() {
  render(
    <ThemeProvider>
      <TestConsumer />
    </ThemeProvider>,
  )
}

describe('ThemeContext', () => {
  beforeEach(() => {
    localStorage.clear()
    document.documentElement.classList.remove('dark')
    vi.unstubAllGlobals()
  })

  it('follows the system by default: dark when the system setting is unknown', () => {
    render(
      <ThemeProvider>
        <TestConsumer />
      </ThemeProvider>,
    )
    expect(screen.getByTestId('theme').textContent).toBe('dark')
  })

  it('reads "light" from localStorage', () => {
    localStorage.setItem(STORAGE_KEY, 'light')
    render(
      <ThemeProvider>
        <TestConsumer />
      </ThemeProvider>,
    )
    expect(screen.getByTestId('theme').textContent).toBe('light')
  })

  it('reads "dark" from localStorage', () => {
    localStorage.setItem(STORAGE_KEY, 'dark')
    render(
      <ThemeProvider>
        <TestConsumer />
      </ThemeProvider>,
    )
    expect(screen.getByTestId('theme').textContent).toBe('dark')
  })

  it('treats an unrecognised localStorage value as System', () => {
    localStorage.setItem(STORAGE_KEY, 'sepia')
    render(
      <ThemeProvider>
        <TestConsumer />
      </ThemeProvider>,
    )
    expect(screen.getByTestId('theme').textContent).toBe('dark')
  })

  it('toggles from dark to light', async () => {
    const user = userEvent.setup()
    render(
      <ThemeProvider>
        <TestConsumer />
      </ThemeProvider>,
    )

    await user.click(screen.getByText('Toggle'))

    expect(screen.getByTestId('theme').textContent).toBe('light')
    expect(localStorage.getItem(STORAGE_KEY)).toBe('light')
    expect(document.documentElement.classList.contains('dark')).toBe(false)
  })

  it('toggles from light to dark', async () => {
    localStorage.setItem(STORAGE_KEY, 'light')
    const user = userEvent.setup()
    render(
      <ThemeProvider>
        <TestConsumer />
      </ThemeProvider>,
    )

    await user.click(screen.getByText('Toggle'))

    expect(screen.getByTestId('theme').textContent).toBe('dark')
    expect(localStorage.getItem(STORAGE_KEY)).toBe('dark')
    expect(document.documentElement.classList.contains('dark')).toBe(true)
  })

  it('persists after double toggle (round-trip)', async () => {
    const user = userEvent.setup()
    render(
      <ThemeProvider>
        <TestConsumer />
      </ThemeProvider>,
    )

    await user.click(screen.getByText('Toggle')) // dark → light
    await user.click(screen.getByText('Toggle')) // light → dark

    expect(screen.getByTestId('theme').textContent).toBe('dark')
    expect(localStorage.getItem(STORAGE_KEY)).toBe('dark')
    expect(document.documentElement.classList.contains('dark')).toBe(true)
  })

  it('handles localStorage getItem throwing', () => {
    const spy = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('SecurityError')
    })

    render(
      <ThemeProvider>
        <TestConsumer />
      </ThemeProvider>,
    )
    expect(screen.getByTestId('theme').textContent).toBe('dark')

    spy.mockRestore()
  })

  it('follows a light system setting, and its changes, while on System', () => {
    const system = mockSystemTheme(false)
    renderConsumer()
    expect(screen.getByTestId('preference').textContent).toBe('system')
    expect(screen.getByTestId('theme').textContent).toBe('light')

    system.set(true)
    expect(screen.getByTestId('theme').textContent).toBe('dark')
    expect(document.documentElement.classList.contains('dark')).toBe(true)
  })

  it('toggling from System picks an explicit theme that ignores the system', async () => {
    const system = mockSystemTheme(true)
    const user = userEvent.setup()
    renderConsumer()

    await user.click(screen.getByText('Toggle'))
    expect(screen.getByTestId('preference').textContent).toBe('light')
    expect(localStorage.getItem(STORAGE_KEY)).toBe('light')

    system.set(false)
    system.set(true)
    expect(screen.getByTestId('theme').textContent).toBe('light')
  })

  it('switching back to System applies the system setting at once', async () => {
    localStorage.setItem(STORAGE_KEY, 'dark')
    mockSystemTheme(false)
    const user = userEvent.setup()
    renderConsumer()

    await user.click(screen.getByText('System'))
    expect(screen.getByTestId('theme').textContent).toBe('light')
    expect(localStorage.getItem(STORAGE_KEY)).toBe('system')
    expect(document.documentElement.classList.contains('dark')).toBe(false)
  })

  it('reports the window colours to the desktop app, and again when the theme changes', async () => {
    const setWindowColors = vi.fn().mockResolvedValue(undefined)
    ;(window as { electronAPI?: unknown }).electronAPI = {
      displayPrefs: {},
      setDisplayPref: vi.fn().mockResolvedValue(undefined),
      setWindowColors,
    }
    document.body.style.backgroundColor = 'rgb(14, 17, 24)'
    document.body.style.color = 'rgb(237, 232, 220)'
    try {
      const user = userEvent.setup()
      renderConsumer()
      expect(setWindowColors).toHaveBeenLastCalledWith({
        background: '#0e1118',
        foreground: '#ede8dc',
      })
      const calls = setWindowColors.mock.calls.length
      await user.click(screen.getByText('Toggle'))
      expect(setWindowColors.mock.calls.length).toBeGreaterThan(calls)
    } finally {
      delete (window as { electronAPI?: unknown }).electronAPI
      document.body.removeAttribute('style')
    }
  })
})
