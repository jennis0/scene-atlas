import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { PalettePicker } from './PalettePicker'
import { PALETTES } from '@/lib/palette'

describe('PalettePicker', () => {
  it('renders every palette as a radio, previewed in its own palette', () => {
    const { container } = render(<PalettePicker value="navy" onChange={() => {}} />)
    expect(screen.getAllByRole('radio')).toHaveLength(PALETTES.length)
    for (const { value } of PALETTES) {
      expect(container.querySelector(`[data-palette="${value}"]`)).not.toBeNull()
    }
  })

  it('marks the current palette checked and makes it the only tab stop', () => {
    render(<PalettePicker value="lapis" onChange={() => {}} />)
    const checked = screen.getByRole('radio', { checked: true })
    expect(checked).toHaveAccessibleName(/Slate & lapis/)
    expect(checked).toHaveAttribute('tabindex', '0')
    expect(screen.getAllByRole('radio').filter((r) => r.tabIndex === 0)).toHaveLength(1)
  })

  it('selects on click', () => {
    const onChange = vi.fn()
    render(<PalettePicker value="navy" onChange={onChange} />)
    fireEvent.click(screen.getByRole('radio', { name: /Walnut & sienna/ }))
    expect(onChange).toHaveBeenCalledWith('sienna')
  })

  it('arrow keys move the selection and wrap around', () => {
    const onChange = vi.fn()
    render(<PalettePicker value="navy" onChange={onChange} />)
    const first = screen.getByRole('radio', { checked: true })
    fireEvent.keyDown(first, { key: 'ArrowRight' })
    expect(onChange).toHaveBeenLastCalledWith(PALETTES[1].value)
    fireEvent.keyDown(first, { key: 'ArrowLeft' })
    expect(onChange).toHaveBeenLastCalledWith(PALETTES[PALETTES.length - 1].value)
  })
})
