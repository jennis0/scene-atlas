import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { GridSizeInput } from './GridSizeInput'

describe('GridSizeInput', () => {
  it('saves a size the API takes', async () => {
    const onChange = vi.fn()
    render(<GridSizeInput width={null} height={20} onChange={onChange} />)
    await userEvent.type(screen.getByPlaceholderText('W'), '30')
    await userEvent.tab()
    expect(onChange).toHaveBeenCalledWith(30, 20)
  })

  it('shows a size out of range as an error and keeps the old one', async () => {
    const onChange = vi.fn()
    render(<GridSizeInput width={10} height={20} onChange={onChange} />)
    const width = screen.getByPlaceholderText('W')
    await userEvent.clear(width)
    await userEvent.type(width, '20000')
    await userEvent.tab()
    expect(onChange).not.toHaveBeenCalled()
    expect(width).toHaveAttribute('aria-invalid', 'true')
    expect(width).toHaveAttribute('title', expect.stringContaining('1 to 10,000'))
  })

  it('clearing a size removes it', async () => {
    const onChange = vi.fn()
    render(<GridSizeInput width={10} height={20} onChange={onChange} />)
    await userEvent.clear(screen.getByPlaceholderText('W'))
    await userEvent.tab()
    expect(onChange).toHaveBeenCalledWith(null, 20)
  })
})
