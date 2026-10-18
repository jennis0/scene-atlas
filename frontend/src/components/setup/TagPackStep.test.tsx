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
    setInstalledPacks: vi.fn(),
  },
}))

const getTagPacks = vi.mocked(tagApi.getTagPacks)
const setInstalledPacks = vi.mocked(tagApi.setInstalledPacks)

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

/** Renders the step mid-wizard; returns its callbacks. */
function renderStep(chosen: string[] | null = null) {
  const onNext = vi.fn()
  const onChosen = vi.fn()
  render(
    <TagPackStep
      nav={{ steps: ['tag-packs', 'model'], index: 0, onNext }}
      chosen={chosen}
      onChosen={onChosen}
    />,
  )
  return { onNext, onChosen }
}

describe('TagPackStep', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    getTagPacks.mockResolvedValue([
      pack('common', true),
      pack('fantasy', false),
      pack('scifi', false),
    ])
    setInstalledPacks.mockResolvedValue([])
  })

  it('starts with every pack selected, Common included and optional', async () => {
    renderStep()
    const common = await screen.findByRole('button', { name: /Common/ })
    expect(common).toBeEnabled()
    for (const name of [/Common/, /Fantasy/, /Scifi/]) {
      expect(screen.getByRole('button', { name })).toHaveAttribute('aria-pressed', 'true')
    }
  })

  it('installs exactly the selection, which can leave Common out', async () => {
    const user = userEvent.setup()
    const { onNext, onChosen } = renderStep()
    await user.click(await screen.findByRole('button', { name: /Common/ }))
    await user.click(screen.getByRole('button', { name: /Scifi/ }))
    expect(screen.getByRole('button', { name: /Common/ })).toHaveAttribute('aria-pressed', 'false')

    await user.click(screen.getByRole('button', { name: 'Continue' }))
    expect(setInstalledPacks).toHaveBeenCalledWith(['fantasy'])
    expect(onChosen).toHaveBeenCalledWith(['fantasy'])
    expect(onNext).toHaveBeenCalled()
  })

  it('allows no packs at all', async () => {
    const user = userEvent.setup()
    const { onNext } = renderStep([])
    await screen.findByRole('button', { name: /Common/ })
    expect(screen.getByRole('button', { name: /Common/ })).toHaveAttribute('aria-pressed', 'false')
    await user.click(screen.getByRole('button', { name: 'Continue' }))
    expect(setInstalledPacks).toHaveBeenCalledWith([])
    expect(onNext).toHaveBeenCalled()
  })

  it('shows the earlier choice after Back', async () => {
    renderStep(['scifi'])
    expect(await screen.findByRole('button', { name: /Scifi/ })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
    expect(screen.getByRole('button', { name: /Fantasy/ })).toHaveAttribute('aria-pressed', 'false')
  })

  it('stays on the step with an explanation when saving fails', async () => {
    setInstalledPacks.mockRejectedValue(
      new AxiosError('Conflict', '409', undefined, undefined, {
        status: 409,
        statusText: 'Conflict',
        data: { detail: 'Tag packs can only be replaced during setup.' },
        headers: {},
        config: { headers: new AxiosHeaders() },
      }),
    )
    const user = userEvent.setup()
    const { onNext } = renderStep()
    await user.click(await screen.findByRole('button', { name: 'Continue' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('only be replaced during setup')
    expect(onNext).not.toHaveBeenCalled()
    await waitFor(() => expect(screen.getByRole('button', { name: 'Continue' })).toBeEnabled())
  })

  it('offers to try again when the packs cannot be loaded', async () => {
    getTagPacks.mockRejectedValueOnce(new Error('offline'))
    renderStep()
    expect(await screen.findByRole('alert')).toHaveTextContent("Couldn't load the tag packs")
    expect(screen.getByRole('button', { name: 'Continue' })).toBeDisabled()
    await userEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByRole('button', { name: /Fantasy/ })).toBeInTheDocument()
  })
})
