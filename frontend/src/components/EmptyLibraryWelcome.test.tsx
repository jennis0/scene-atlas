import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { EmptyLibraryWelcome } from './EmptyLibraryWelcome'

describe('EmptyLibraryWelcome', () => {
  it('says maps are being added while the linked folder is scanned, in place of the prompt', () => {
    render(<EmptyLibraryWelcome embeddingReady={false} addingMaps onImport={vi.fn()} />)
    expect(screen.getByRole('heading', { name: 'Adding your maps…' })).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('A large folder can take a few hours.')
    expect(screen.getByRole('status')).toHaveTextContent('Getting the search model ready')
    expect(screen.queryByRole('button', { name: /Import/ })).not.toBeInTheDocument()
  })
})
