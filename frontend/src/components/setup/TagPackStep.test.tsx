import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AxiosError, AxiosHeaders } from 'axios'
import { tagApi } from '@/lib/api/tagApi'
import type { TagPack } from '@/types'
import { TagPackStep } from './TagPackStep'

vi.mock('@/lib/api/tagApi', () => ({
  tagApi: {
    getTagPacks: vi.fn(),
    importMultipleTagPacks: vi.fn(),
  },
}))

const getTagPacks = vi.mocked(tagApi.getTagPacks)
const importMultiple = vi.mocked(tagApi.importMultipleTagPacks)

function pack(name: string, imported: boolean): TagPack {
  return {
    name,
    label: name[0].toUpperCase() + name.slice(1),
    description: `${name} tags`,
    tag_count: 10,
    imported,
    new_tags: imported ? 0 : 10,
  }
}

/** Renders the step mid-wizard; returns its onNext, which "completes" the step. */
function renderStep(onNext = vi.fn()) {
  render(<TagPackStep nav={{ steps: ['tag-packs', 'model'], index: 0, onNext }} />)
  return onNext
}

describe('TagPackStep', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    getTagPacks.mockResolvedValue([
      pack('common', true),
      pack('fantasy', false),
      pack('scifi', false),
    ])
  })

  it('shows common as included and pre-selects the genre packs', async () => {
    renderStep()
    const common = await screen.findByRole('button', { name: /Common/ })
    expect(common).toBeDisabled()
    expect(common).toHaveTextContent('(included)')
    expect(screen.getByRole('button', { name: /Fantasy/ })).toBeEnabled()
  })

  it('exposes each pack as a toggle with its selected state', async () => {
    renderStep()
    const fantasy = await screen.findByRole('button', { name: /Fantasy/ })
    expect(fantasy).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: /Common/ })).toHaveAttribute('aria-pressed', 'true')

    await userEvent.click(fantasy)
    expect(fantasy).toHaveAttribute('aria-pressed', 'false')
  })

  it('marks genre packs imported earlier (e.g. before Back) as added', async () => {
    getTagPacks.mockResolvedValue([pack('common', true), pack('fantasy', true)])
    renderStep()
    expect(await screen.findByRole('button', { name: /Fantasy/ })).toHaveTextContent('(added)')
  })

  it('moves on without importing when nothing is selected', async () => {
    getTagPacks.mockResolvedValue([pack('common', true), pack('fantasy', false)])
    const onNext = renderStep()
    await userEvent.click(await screen.findByRole('button', { name: /Fantasy/ }))
    await userEvent.click(screen.getByRole('button', { name: 'Continue' }))
    expect(importMultiple).not.toHaveBeenCalled()
    expect(onNext).toHaveBeenCalled()
  })

  it('offers to try again when the packs cannot be loaded', async () => {
    getTagPacks.mockRejectedValueOnce(new Error('offline'))
    renderStep()
    expect(await screen.findByRole('alert')).toHaveTextContent("Couldn't load the tag packs")
    expect(screen.getByRole('button', { name: 'Continue' })).toBeDisabled()
    await userEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByRole('button', { name: /Fantasy/ })).toBeInTheDocument()
  })

  it('imports the selected packs and moves on', async () => {
    importMultiple.mockResolvedValue({ imported: ['fantasy', 'scifi'], errors: [] })
    const onNext = renderStep()
    await userEvent.click(await screen.findByRole('button', { name: 'Continue' }))

    expect(importMultiple).toHaveBeenCalledWith(['fantasy', 'scifi'])
    await waitFor(() => expect(onNext).toHaveBeenCalled())
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('surfaces per-pack errors and keeps the failed pack selected for retry', async () => {
    importMultiple.mockResolvedValueOnce({
      imported: ['fantasy'],
      errors: ['scifi: database is locked'],
    })
    const onNext = renderStep()
    await screen.findByRole('button', { name: /Fantasy/ })
    getTagPacks.mockResolvedValue([
      pack('common', true),
      pack('fantasy', true),
      pack('scifi', false),
    ])
    await userEvent.click(screen.getByRole('button', { name: 'Continue' }))

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('scifi: database is locked')
    expect(onNext).not.toHaveBeenCalled()
    await waitFor(() => expect(screen.getByRole('button', { name: /Fantasy/ })).toBeDisabled())

    importMultiple.mockResolvedValueOnce({ imported: ['scifi'], errors: [] })
    await userEvent.click(await screen.findByRole('button', { name: 'Try again' }))
    expect(importMultiple).toHaveBeenLastCalledWith(['scifi'])
    await waitFor(() => expect(onNext).toHaveBeenCalled())
  })

  it('explains a rate-limited request', async () => {
    importMultiple.mockRejectedValue(
      new AxiosError('Too Many Requests', '429', undefined, undefined, {
        status: 429,
        statusText: 'Too Many Requests',
        data: { error: 'Rate limit exceeded' },
        headers: {},
        config: { headers: new AxiosHeaders() },
      }),
    )
    const onNext = renderStep()
    await userEvent.click(await screen.findByRole('button', { name: 'Continue' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Too many attempts')
    expect(onNext).not.toHaveBeenCalled()
  })

  it('lets the user skip after a failure', async () => {
    importMultiple.mockResolvedValue({ imported: [], errors: ['fantasy: boom'] })
    const onNext = renderStep()
    await userEvent.click(await screen.findByRole('button', { name: 'Continue' }))
    await screen.findByRole('alert')

    await userEvent.click(screen.getByRole('button', { name: 'Skip for now' }))
    await waitFor(() => expect(onNext).toHaveBeenCalled())
  })
})
