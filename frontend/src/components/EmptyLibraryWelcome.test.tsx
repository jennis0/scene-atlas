import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { counts, jobSummary } from '@/test/importFakes'
import { EmptyLibraryWelcome } from './EmptyLibraryWelcome'

describe('EmptyLibraryWelcome', () => {
  it('says images are being added while the linked folder is scanned, in place of the prompt', () => {
    render(<EmptyLibraryWelcome embeddingReady={false} addingMaps onImport={vi.fn()} />)
    expect(screen.getByRole('heading', { name: 'Adding your images…' })).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent(
      "They appear here once they're all added and grouped.",
    )
    expect(screen.getByRole('status')).toHaveTextContent('Getting the search model ready')
    expect(screen.queryByRole('button', { name: /Import/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument() // no import yet
  })

  it("shows the linked import's progress and time left, outside the live region", () => {
    const job = jobSummary({
      linked: true,
      planned: true,
      counts: counts({ total: 48000, done: 12000, ready: 36000 }),
    })
    render(
      <EmptyLibraryWelcome
        embeddingReady
        addingMaps
        linkedJob={job}
        secondsPerItem={0.5}
        onImport={vi.fn()}
      />,
    )
    expect(screen.getByRole('progressbar', { name: 'Files processed' })).toHaveAttribute(
      'aria-valuenow',
      '12000',
    )
    // 36,000 files at 0.5 s each
    expect(screen.getByText('12,000 of 48,000 files done · about 5 h left')).toBeInTheDocument()
    expect(screen.getByRole('status')).not.toHaveTextContent('files done')
  })

  it('says the groups are being identified once every file is in', () => {
    const job = jobSummary({
      linked: true,
      planned: true,
      status: 'grouping',
      counts: counts({ total: 10, done: 10 }),
    })
    render(<EmptyLibraryWelcome embeddingReady addingMaps linkedJob={job} onImport={vi.fn()} />)
    expect(screen.getByText('Identifying groups…')).toBeInTheDocument()
  })
})
