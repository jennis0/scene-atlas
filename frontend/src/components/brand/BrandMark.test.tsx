import { render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { BrandMark } from './BrandMark'

describe('BrandMark', () => {
  it('draws the band in the accent and the pages in the text colour, hidden from screen readers', () => {
    const { container } = render(<BrandMark className="h-4" />)
    const svg = container.querySelector('svg')
    expect(svg).toHaveAttribute('aria-hidden', 'true')
    expect(svg).toHaveClass('h-4')
    expect(container.querySelectorAll('path.fill-primary')).toHaveLength(2)
    expect(container.querySelectorAll('path.fill-foreground')).toHaveLength(2)
  })
})
