import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AxiosError, AxiosHeaders } from 'axios'
import { tagApi } from '@/lib/api/tagApi'
import type { TagPack } from '@/types'
import { TagPackSetupStep } from './TagPackSetupStep'

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

function renderStep(onComplete = vi.fn()) {
  render(
    <TagPackSetupStep
      modelProgressMessage={null}
      modelProgressPct={null}
      modelComplete={true}
      onComplete={onComplete}
    />,
  )
  return onComplete
}

describe('TagPackSetupStep', () => {
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

  it('imports the selected packs and completes', async () => {
    importMultiple.mockResolvedValue({ imported: ['fantasy', 'scifi'], errors: [] })
    const onComplete = renderStep()
    await userEvent.click(await screen.findByRole('button', { name: 'Continue' }))

    expect(importMultiple).toHaveBeenCalledWith(['fantasy', 'scifi'])
    await waitFor(() => expect(onComplete).toHaveBeenCalled())
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('surfaces per-pack errors and keeps the failed pack selected for retry', async () => {
    importMultiple.mockResolvedValueOnce({
      imported: ['fantasy'],
      errors: ['scifi: database is locked'],
    })
    const onComplete = renderStep()
    await screen.findByRole('button', { name: /Fantasy/ })
    getTagPacks.mockResolvedValue([
      pack('common', true),
      pack('fantasy', true),
      pack('scifi', false),
    ])
    await userEvent.click(screen.getByRole('button', { name: 'Continue' }))

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('scifi: database is locked')
    expect(onComplete).not.toHaveBeenCalled()
    await waitFor(() => expect(screen.getByRole('button', { name: /Fantasy/ })).toBeDisabled())

    importMultiple.mockResolvedValueOnce({ imported: ['scifi'], errors: [] })
    await userEvent.click(await screen.findByRole('button', { name: 'Try again' }))
    expect(importMultiple).toHaveBeenLastCalledWith(['scifi'])
    await waitFor(() => expect(onComplete).toHaveBeenCalled())
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
    const onComplete = renderStep()
    await userEvent.click(await screen.findByRole('button', { name: 'Continue' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Too many attempts')
    expect(onComplete).not.toHaveBeenCalled()
  })

  it('lets the user skip after a failure', async () => {
    importMultiple.mockResolvedValue({ imported: [], errors: ['fantasy: boom'] })
    const onComplete = renderStep()
    await userEvent.click(await screen.findByRole('button', { name: 'Continue' }))
    await screen.findByRole('alert')

    await userEvent.click(screen.getByRole('button', { name: 'Skip for now' }))
    await waitFor(() => expect(onComplete).toHaveBeenCalled())
  })
})
