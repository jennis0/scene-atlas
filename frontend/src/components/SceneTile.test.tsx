import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { SceneTile } from './SceneTile'
import type { Image } from '@/types'

const image = {
  id: 1,
  storage_key: 'ab/cd.webp',
  media_type: 'image',
  colors: [],
} as unknown as Image

describe('SceneTile', () => {
  it('is one button, named by its caption, that opens with the keyboard', async () => {
    const onClick = vi.fn()
    render(
      <SceneTile
        image={image}
        primaryText="Abandoned Mine"
        secondaryText="Goblin Night"
        authorText="Czepeku"
        onClick={onClick}
      />,
    )
    const tile = screen.getByRole('button', { name: 'Abandoned Mine, Goblin Night, by Czepeku' })
    await userEvent.tab()
    expect(tile).toHaveFocus()
    await userEvent.keyboard('{Enter}')
    expect(onClick).toHaveBeenCalledOnce()
    // The caption and thumbnail aren't announced a second time
    expect(screen.queryByRole('img')).not.toBeInTheDocument()
  })

  it('puts the group and variant on one line, the author below', () => {
    render(
      <SceneTile
        image={image}
        primaryText="Czepeku"
        variantText="Abandoned Mine · Goblin Night"
        authorText="Czepeku Maps"
        onClick={vi.fn()}
      />,
    )
    expect(screen.getByText('Czepeku').closest('p')).toHaveTextContent(
      'Czepeku – Abandoned Mine · Goblin Night',
    )
    expect(
      screen.getByRole('button', {
        name: 'Czepeku, Abandoned Mine · Goblin Night, by Czepeku Maps',
      }),
    ).toBeInTheDocument()
  })

  it('marks the current scene', () => {
    render(<SceneTile image={image} primaryText="Snow" onClick={vi.fn()} isActive />)
    expect(screen.getByRole('button', { name: 'Snow' })).toHaveAttribute('aria-current', 'true')
  })
})
