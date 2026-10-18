import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { TypeCounts } from './TypeCounts'

describe('TypeCounts', () => {
  it('shows each non-zero kind with a readable description', () => {
    render(<TypeCounts maps={14} scenes={2} skipped={3} />)
    const label = '14 maps, 2 scenes, 3 skipped by Auto'
    expect(screen.getByTitle(label)).toBeInTheDocument()
    expect(screen.getByText(label)).toHaveClass('sr-only')
  })

  it('leaves out kinds with nothing in them', () => {
    render(<TypeCounts maps={0} scenes={1} />)
    expect(screen.getByTitle('1 scene')).toBeInTheDocument()
  })

  it('renders nothing for an empty group', () => {
    const { container } = render(<TypeCounts maps={0} scenes={0} skipped={0} />)
    expect(container).toBeEmptyDOMElement()
  })
})
