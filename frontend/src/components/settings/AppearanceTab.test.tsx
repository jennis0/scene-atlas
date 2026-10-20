import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ThemeProvider } from '@/contexts/ThemeContext'
import { AppearanceTab } from './AppearanceTab'

const mode = vi.hoisted(() => ({ isApp: false }))
vi.mock('@/lib/appMode', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/appMode')>()),
  get isApp() {
    return mode.isApp
  },
}))

describe('AppearanceTab', () => {
  afterEach(() => {
    mode.isApp = false
    delete (window as { electronAPI?: unknown }).electronAPI
  })

  it('offers zoom in the desktop app only', async () => {
    const user = userEvent.setup()
    const setZoom = vi.fn()
    ;(window as { electronAPI?: unknown }).electronAPI = {
      platform: 'linux',
      setZoom,
      setDisplayPref: vi.fn().mockResolvedValue(undefined),
    }
    mode.isApp = true
    const { unmount } = render(
      <ThemeProvider>
        <AppearanceTab />
      </ThemeProvider>,
    )
    expect(screen.getByText(/Ctrl \+ and Ctrl − also zoom/)).toBeInTheDocument()
    await user.click(screen.getByRole('radio', { name: '150%' }))
    expect(setZoom).toHaveBeenCalledWith(150)
    expect(localStorage.getItem('scene-atlas-zoom')).toBe('150')
    expect(screen.getByRole('radio', { name: '150%' })).toBeChecked()
    unmount()

    mode.isApp = false
    render(
      <ThemeProvider>
        <AppearanceTab />
      </ThemeProvider>,
    )
    expect(screen.queryByRole('radiogroup', { name: 'Zoom' })).not.toBeInTheDocument()
  })

  beforeEach(() => {
    localStorage.clear()
    document.documentElement.classList.add('dark')
    delete document.documentElement.dataset.palette
    delete document.documentElement.dataset.textSize
    delete document.documentElement.dataset.compactHeader
  })

  it('applies every choice at once and saves them on this device', async () => {
    const user = userEvent.setup()
    render(
      <ThemeProvider>
        <AppearanceTab />
      </ThemeProvider>,
    )

    await user.click(screen.getByRole('radio', { name: 'Light' }))
    expect(document.documentElement.classList.contains('dark')).toBe(false)
    expect(localStorage.getItem('scene-atlas-theme')).toBe('light')

    await user.click(screen.getByRole('radio', { name: /Slate/ }))
    expect(document.documentElement.dataset.palette).toBe('lapis')
    expect(localStorage.getItem('scene-atlas-palette')).toBe('lapis')

    await user.click(screen.getByRole('radio', { name: 'Large' }))
    expect(document.documentElement.dataset.textSize).toBe('large')
    expect(localStorage.getItem('scene-atlas-text-size')).toBe('large')

    await user.click(screen.getByRole('radio', { name: 'On' }))
    expect(document.documentElement.dataset.compactHeader).toBe('on')
    expect(localStorage.getItem('scene-atlas-compact-header')).toBe('on')
  })
})
