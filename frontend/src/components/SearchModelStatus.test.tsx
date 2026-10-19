import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { SearchModelStatus } from './SearchModelStatus'

describe('SearchModelStatus', () => {
  it('shows nothing once the model is ready', () => {
    const { container } = render(<SearchModelStatus status="ready" />)
    expect(container).toBeEmptyDOMElement()
  })

  it('announces loading', () => {
    render(<SearchModelStatus status="loading" />)
    expect(screen.getByRole('status')).toHaveTextContent('Search model loading')
  })

  it.each([
    ['missing', 'Search model not downloaded'],
    ['error', 'Search model unavailable'],
  ] as const)('explains the %s state from the keyboard', async (status, label) => {
    render(
      <SearchModelStatus status={status} message="Choose one under Search Model in Settings." />,
    )
    const pill = screen.getByRole('button', { name: label })
    pill.focus()
    await userEvent.keyboard('{Enter}')
    expect(await screen.findByText('Choose one under Search Model in Settings.')).toBeVisible()
  })
})
