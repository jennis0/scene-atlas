import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { TagChip } from './TagChip'

describe('TagChip', () => {
  it('shows the value with its category as the tooltip', () => {
    render(<TagChip category="biome" value="forest" />)
    expect(screen.getByText('forest').parentElement).toHaveAttribute('title', 'biome')
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })

  it('removes the tag unless disabled', async () => {
    const onRemove = vi.fn()
    const { rerender } = render(<TagChip category="biome" value="forest" onRemove={onRemove} />)
    await userEvent.click(screen.getByTitle('Remove biome: forest'))
    expect(onRemove).toHaveBeenCalledTimes(1)

    rerender(<TagChip category="biome" value="forest" onRemove={onRemove} removeDisabled />)
    expect(screen.getByTitle('Remove biome: forest')).toBeDisabled()
  })
})
