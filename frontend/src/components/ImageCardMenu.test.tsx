import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '@/test/renderWithProviders'
import { ImageCardMenu } from './ImageCardMenu'
import type { Image } from '@/types'

vi.mock('@/lib/api', () => ({
  getImageUrl: vi.fn((img: { id: number }) => `/api/v1/images/${img.id}/file`),
}))
vi.mock('@/lib/download', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/download')>()),
  downloadFile: vi.fn().mockResolvedValue(undefined),
}))

import { downloadFile } from '@/lib/download'

const image = {
  id: 3,
  name: 'Entrance',
  filename: 'cave.png',
  group_id: 5,
  group_name: 'Caves',
  subgroup: null,
  gridded: false,
} as Image

function setup(overrides: Partial<Image> = {}) {
  const actions = { onEditGroup: vi.fn(), onMove: vi.fn(), onDelete: vi.fn() }
  const user = userEvent.setup()
  renderWithProviders(
    <div className="group/card relative">
      <ImageCardMenu image={{ ...image, ...overrides }} actions={actions} />
    </div>,
  )
  return { user, actions }
}

describe('ImageCardMenu', () => {
  beforeEach(() => vi.clearAllMocks())

  it.each([
    ['Edit group', 'onEditGroup'],
    ['Move to group…', 'onMove'],
    ['Delete', 'onDelete'],
  ] as const)('%s calls %s with the image', async (item, handler) => {
    const { user, actions } = setup()
    await user.click(screen.getByRole('button', { name: 'Actions for Caves Entrance' }))
    await user.click(screen.getByRole('menuitem', { name: item }))
    expect(actions[handler]).toHaveBeenCalledWith(expect.objectContaining({ id: 3 }))
  })

  it('downloads the image itself', async () => {
    const { user } = setup()
    await user.click(screen.getByRole('button', { name: 'Actions for Caves Entrance' }))
    await user.click(screen.getByRole('menuitem', { name: 'Download' }))
    await waitFor(() =>
      expect(downloadFile).toHaveBeenCalledWith('/api/v1/images/3/file', expect.any(String)),
    )
  })

  it('offers no group actions for an image without a group', async () => {
    const { user } = setup({ group_id: null, group_name: null })
    await user.click(screen.getByRole('button', { name: 'Actions for Entrance' }))
    expect(screen.queryByRole('menuitem', { name: 'Edit group' })).not.toBeInTheDocument()
    expect(screen.queryByRole('menuitem', { name: 'Move to group…' })).not.toBeInTheDocument()
    expect(screen.getByRole('menuitem', { name: 'Download' })).toBeInTheDocument()
  })
})
