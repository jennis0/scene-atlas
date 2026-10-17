import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ThemeProvider } from '@/contexts/ThemeContext'
import { AppearanceTab } from './AppearanceTab'

describe('AppearanceTab', () => {
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

    await user.click(screen.getByRole('radio', { name: /Slate & lapis/ }))
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
