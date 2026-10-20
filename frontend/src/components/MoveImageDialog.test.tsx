import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { toast } from 'sonner'
import { renderWithProviders } from '@/test/renderWithProviders'
import { MoveImageDialog } from './MoveImageDialog'
import type { Image } from '@/types'

vi.mock('@/lib/api', () => ({
  groupApi: { search: vi.fn(), moveImages: vi.fn() },
  getThumbnailUrlById: vi.fn((id: number) => `/thumb/${id}`),
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

import { groupApi } from '@/lib/api'

const image = {
  id: 7,
  name: 'Snowy',
  author: 'Cartographer',
  group_id: 10,
  group_name: 'Frozen Lake',
} as Image

const caves = { id: 20, base_name: 'Frozen Lake', author: 'Cartographer', image_count: 4 }

function setup(props: Partial<Parameters<typeof MoveImageDialog>[0]> = {}) {
  const handlers = { onClose: vi.fn(), onMoved: vi.fn() }
  const user = userEvent.setup()
  renderWithProviders(<MoveImageDialog image={image} {...handlers} {...props} />)
  return { user, ...handlers }
}

describe('MoveImageDialog', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(groupApi.search).mockResolvedValue({ groups: [caves], total: 1 } as never)
    vi.mocked(groupApi.moveImages).mockResolvedValue({
      source_group_id: 10,
      target_group_id: 20,
      target_group_name: 'Frozen Lake',
      images_moved: 1,
      source_group_deleted: false,
    })
  })

  it('lists other groups ranked against the image and group name', async () => {
    setup()
    expect(await screen.findByText('Frozen Lake')).toBeInTheDocument()
    expect(groupApi.search).toHaveBeenCalledWith('', 10, 20, 'Frozen Lake Snowy')
  })

  it('moves the image into the chosen group', async () => {
    const { user, onClose, onMoved } = setup()
    await user.click(await screen.findByText('Frozen Lake'))
    await user.click(screen.getByRole('button', { name: 'Move' }))
    await waitFor(() => expect(groupApi.moveImages).toHaveBeenCalledWith(10, { groupId: 20 }, [7]))
    await waitFor(() => expect(onClose).toHaveBeenCalled())
    expect(onMoved).toHaveBeenCalled()
    expect(toast.success).toHaveBeenCalledWith('Moved to Frozen Lake')
  })

  it('moves the image into a new group named after its group and itself', async () => {
    const { user } = setup()
    await user.click(screen.getByRole('button', { name: /New group: Frozen Lake Snowy/ }))
    await user.click(screen.getByRole('button', { name: 'Move' }))
    await waitFor(() =>
      expect(groupApi.moveImages).toHaveBeenCalledWith(
        10,
        { newGroupName: 'Frozen Lake Snowy' },
        [7],
      ),
    )
  })

  it('names the new group from the search text when there is some', async () => {
    const { user } = setup()
    await user.type(screen.getByPlaceholderText('Search groups…'), 'Winter Lake ')
    await user.click(screen.getByRole('button', { name: /New group: Winter Lake/ }))
    await user.click(screen.getByRole('button', { name: 'Move' }))
    await waitFor(() =>
      expect(groupApi.moveImages).toHaveBeenCalledWith(10, { newGroupName: 'Winter Lake' }, [7]),
    )
  })

  it('needs a choice before moving', async () => {
    setup()
    await screen.findByText('Frozen Lake')
    expect(screen.getByRole('button', { name: 'Move' })).toBeDisabled()
  })

  it('stays open and reports a failed move', async () => {
    vi.mocked(groupApi.moveImages).mockRejectedValue(new Error('boom'))
    const { user, onClose } = setup()
    await user.click(await screen.findByText('Frozen Lake'))
    await user.click(screen.getByRole('button', { name: 'Move' }))
    await waitFor(() => expect(toast.error).toHaveBeenCalled())
    expect(onClose).not.toHaveBeenCalled()
  })

  it('is closed without an image', () => {
    setup({ image: null })
    expect(screen.queryByText('Move to Group')).not.toBeInTheDocument()
  })
})
