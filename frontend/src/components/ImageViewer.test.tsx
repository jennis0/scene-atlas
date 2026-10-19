import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, waitFor, within, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '@/test/renderWithProviders'
import { ImageViewer } from './ImageViewer'
import type { Image } from '@/types'

vi.mock('@/lib/api', () => ({
  imageApi: {
    get: vi.fn(),
    getScenes: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn().mockResolvedValue(undefined),
  },
  tagApi: {
    getCategories: vi.fn().mockResolvedValue([]),
    addToImage: vi.fn().mockResolvedValue(undefined),
    removeTag: vi.fn().mockResolvedValue(undefined),
  },
  getImageUrl: vi.fn((img: { id: number }) => `/api/v1/images/${img.id}/file`),
  getThumbnailUrl: vi.fn((img: { id: number }) => `/api/v1/images/${img.id}/thumbnail`),
  getGroupDownloadUrl: vi.fn((id: number) => `/api/v1/groups/${id}/download`),
}))

vi.mock('@/lib/download', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/download')>()),
  downloadFile: vi.fn().mockResolvedValue(undefined),
}))

import { imageApi, tagApi } from '@/lib/api'
import { downloadFile } from '@/lib/download'

function makeImage(overrides: Partial<Image> = {}): Image {
  return {
    id: 1,
    storage_key: 'ab/cd.webp',
    file_state: 'ok',
    filename: 'forest_clearing.png',
    author: 'Cartographer',
    name: 'Forest Clearing',
    group_id: 10,
    group_name: 'Forest Pack',
    group_image_count: 1,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    file_size: 2 * 1024 * 1024,
    width: 2000,
    height: 1500,
    gridded: true,
    grid_width: 20,
    grid_height: 15,
    grid_type: 'square',
    grid_confidence: 1,
    subgroup: null,
    image_type: 'battlemap',
    thumbnail_key: null,
    media_type: 'image',
    tags: [],
    colors: [],
    ...overrides,
  }
}

const tag = (id: number, category: string, value: string) => ({
  id,
  image_id: 0,
  category,
  value,
  confidence: 1,
  source: 'manual',
})

function setup(image: Image, scenes: Image[] = [image], props: Record<string, unknown> = {}) {
  vi.mocked(imageApi.get).mockResolvedValue(image)
  vi.mocked(imageApi.getScenes).mockResolvedValue(scenes)
  vi.mocked(imageApi.patch).mockImplementation(
    async (_id, payload) => ({ ...image, ...payload }) as Image,
  )
  const handlers = {
    onClose: vi.fn(),
    onNext: vi.fn(),
    onPrevious: vi.fn(),
    onImageChange: vi.fn(),
    onEditGroup: vi.fn(),
    onDelete: vi.fn(),
  }
  const user = userEvent.setup()
  renderWithProviders(<ImageViewer image={image} {...handlers} {...props} />)
  return { user, ...handlers }
}

const viewer = () => screen.getByTestId('image-viewer')

describe('ImageViewer', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe('metadata', () => {
    it('shows name, group, author, filename stem and size', () => {
      setup(makeImage())
      expect(screen.getByRole('heading', { name: 'Forest Clearing' })).toBeInTheDocument()
      expect(screen.getByText('Forest Pack')).toBeInTheDocument()
      expect(screen.getByText('by Cartographer')).toBeInTheDocument()
      expect(screen.getByText('forest_clearing')).toBeInTheDocument()
      expect(screen.getByText('2000×1500 · 2.0 MB')).toBeInTheDocument()
      expect(within(viewer()).getAllByRole('img')[0]).toHaveAttribute('alt', 'Forest Clearing')
    })

    it('hides the group name when it equals the image name', () => {
      setup(makeImage({ group_name: 'Forest Clearing' }))
      expect(screen.getAllByText('Forest Clearing')).toHaveLength(1)
    })

    it('renders a video element for video media', () => {
      setup(makeImage({ media_type: 'video' }))
      expect(viewer().querySelector('video')).not.toBeNull()
    })

    it('hides the grid row for scenes', () => {
      setup(makeImage({ image_type: 'scene' }))
      expect(screen.queryByText('Grid')).not.toBeInTheDocument()
    })

    it('patches the image type from the Map/Scene toggle', async () => {
      const { user } = setup(makeImage())
      await user.click(screen.getByRole('button', { name: 'Scene' }))
      expect(imageApi.patch).toHaveBeenCalledWith(1, { image_type: 'scene' })
    })

    it('clears the subgroup', async () => {
      const { user } = setup(makeImage({ subgroup: 'winter' }))
      await user.click(screen.getByTitle('Clear subgroup'))
      expect(imageApi.patch).toHaveBeenCalledWith(1, { subgroup: null })
    })

    it('removes a tag', async () => {
      const { user } = setup(makeImage({ tags: [tag(55, 'biome', 'forest')] }))
      await user.click(screen.getByTitle('Remove biome: forest'))
      await waitFor(() => expect(tagApi.removeTag).toHaveBeenCalled())
      expect(vi.mocked(tagApi.removeTag).mock.calls[0][0]).toBe(55)
    })

    it('calls onEditGroup with the group id', async () => {
      const { user, onEditGroup } = setup(makeImage())
      await user.click(screen.getByRole('button', { name: /Edit group/ }))
      expect(onEditGroup).toHaveBeenCalledWith(10)
    })
  })

  describe('rename', () => {
    it('saves a new name on Enter', async () => {
      const { user, onImageChange } = setup(makeImage())
      await user.click(screen.getByTitle('Click to rename'))
      const input = within(viewer()).getByDisplayValue('Forest Clearing')
      await user.clear(input)
      await user.type(input, 'Glade{Enter}')
      expect(imageApi.patch).toHaveBeenCalledWith(1, { name: 'Glade' })
      await waitFor(() =>
        expect(onImageChange).toHaveBeenCalledWith(expect.objectContaining({ name: 'Glade' })),
      )
    })

    it('reverts on Escape without saving or closing the viewer', async () => {
      const { user, onClose } = setup(makeImage())
      await user.click(screen.getByTitle('Rename'))
      const input = within(viewer()).getByDisplayValue('Forest Clearing')
      await user.type(input, ' edited{Escape}')
      expect(imageApi.patch).not.toHaveBeenCalled()
      expect(onClose).not.toHaveBeenCalled()
      expect(screen.getByRole('heading', { name: 'Forest Clearing' })).toBeInTheDocument()
    })
  })

  describe('keyboard', () => {
    it('closes on Escape and navigates with the arrow keys', async () => {
      const { user, onClose, onNext, onPrevious } = setup(makeImage())
      await user.keyboard('{ArrowRight}')
      expect(onNext).toHaveBeenCalledTimes(1)
      await user.keyboard('{ArrowLeft}')
      expect(onPrevious).toHaveBeenCalledTimes(1)
      await user.keyboard('{Escape}')
      expect(onClose).toHaveBeenCalledTimes(1)
    })

    it('ignores keys typed into an input', async () => {
      const scenes = [makeImage(), makeImage({ id: 2, name: 'Other' })]
      const { user, onClose, onNext } = setup(scenes[0], scenes)
      const filter = await screen.findByPlaceholderText('Filter…')
      await user.type(filter, '{ArrowRight}{Escape}')
      expect(onNext).not.toHaveBeenCalled()
      expect(onClose).not.toHaveBeenCalled()
    })

    it('defers to an open dialog', async () => {
      const { user, onClose, onNext } = setup(makeImage())
      await user.click(screen.getByTitle('Delete image'))
      expect(screen.getByRole('dialog', { name: 'Delete Image' })).toBeInTheDocument()
      await user.keyboard('{ArrowRight}')
      await user.keyboard('{Escape}')
      expect(onNext).not.toHaveBeenCalled()
      expect(onClose).not.toHaveBeenCalled()
      await waitFor(() =>
        expect(screen.queryByRole('dialog', { name: 'Delete Image' })).not.toBeInTheDocument(),
      )
    })

    it('closes when the backdrop is clicked but not the content', async () => {
      const { user, onClose } = setup(makeImage())
      await user.click(screen.getByText('by Cartographer'))
      expect(onClose).not.toHaveBeenCalled()
      fireEvent.click(viewer())
      expect(onClose).toHaveBeenCalledTimes(1)
    })
  })

  describe('originals that cannot be read', () => {
    it.each([
      ['missing', 'The original file is missing.'],
      ['offline', "The folder this map is in isn't available."],
    ] as const)('shows the thumbnail when the file is %s, and no download', (file_state, text) => {
      setup(makeImage({ file_state }))
      expect(screen.getByRole('status')).toHaveTextContent(text)
      expect(within(viewer()).getAllByRole('img')[0]).toHaveAttribute(
        'src',
        '/api/v1/images/1/thumbnail',
      )
      expect(screen.getByRole('button', { name: 'Download image' })).toBeDisabled()
    })

    it('shows the original when it can be read', () => {
      setup(makeImage())
      expect(within(viewer()).getAllByRole('img')[0]).toHaveAttribute(
        'src',
        '/api/v1/images/1/file',
      )
      expect(screen.getByRole('button', { name: 'Download image' })).toBeEnabled()
    })
  })

  describe('downloads', () => {
    it('names the image download from group, subgroup, name and grid', async () => {
      const { user } = setup(makeImage({ subgroup: 'night', name: 'Gate: North' }))
      await user.click(screen.getByTitle('Download image'))
      expect(downloadFile).toHaveBeenCalledWith(
        '/api/v1/images/1/file',
        'Forest Pack - night - Gate North - Grid 20x15.webp',
      )
    })

    it('labels gridless and hex maps', async () => {
      const { user } = setup(makeImage({ gridded: false, storage_key: '', group_name: null }))
      await user.click(screen.getByTitle('Download image'))
      expect(downloadFile).toHaveBeenCalledWith(
        '/api/v1/images/1/file',
        'Forest Clearing - No Grid.png',
      )
    })

    it('downloads the group as a zip', async () => {
      const { user } = setup(makeImage())
      await user.click(screen.getByRole('button', { name: /Download group/ }))
      expect(downloadFile).toHaveBeenCalledWith('/api/v1/groups/10/download', 'Forest Pack.zip')
    })
  })

  describe('accessibility', () => {
    it('is a modal dialog named after the image, focused on open', () => {
      setup(makeImage())
      const dialog = screen.getByRole('dialog', { name: 'Forest Clearing' })
      expect(dialog).toHaveAttribute('aria-modal', 'true')
      expect(dialog).toHaveFocus()
    })

    it('names its icon-only controls', () => {
      setup(makeImage(), [makeImage()], { onNext: vi.fn(), onPrevious: vi.fn() })
      expect(screen.getByRole('button', { name: 'Previous image' })).toBeInTheDocument()
      expect(screen.getByRole('button', { name: 'Next image' })).toBeInTheDocument()
    })

    it('toggles the detected grid overlay with its button and the G key', async () => {
      localStorage.removeItem('viewer-grid-overlay')
      const { user } = setup(makeImage())
      const toggle = screen.getByRole('button', { name: /Grid 20×15/ })
      expect(toggle).toHaveAttribute('aria-pressed', 'false')
      await user.click(toggle)
      expect(toggle).toHaveAttribute('aria-pressed', 'true')
      await user.keyboard('g')
      expect(toggle).toHaveAttribute('aria-pressed', 'false')
      localStorage.removeItem('viewer-grid-overlay')
    })

    it('offers no grid overlay without a detected square grid', () => {
      setup(makeImage({ gridded: false, grid_type: null }))
      expect(screen.queryByRole('button', { name: /Grid \d/ })).not.toBeInTheDocument()
    })

    it('exposes which type and grid are selected', () => {
      setup(makeImage())
      expect(screen.getByRole('button', { name: 'Map' })).toHaveAttribute('aria-pressed', 'true')
      expect(screen.getByRole('button', { name: 'Scene' })).toHaveAttribute('aria-pressed', 'false')
      expect(screen.getByRole('button', { name: 'Square' })).toHaveAttribute('aria-pressed', 'true')
      expect(screen.getByRole('button', { name: 'Unknown' })).toHaveAttribute(
        'aria-pressed',
        'false',
      )
    })
  })

  describe('scene panel', () => {
    const scenes = [
      makeImage({ id: 1, name: 'Day', subgroup: 'summer', filename: 'day.png' }),
      makeImage({ id: 2, name: 'Night', subgroup: 'summer', filename: 'night_alt.png' }),
      makeImage({
        id: 3,
        name: 'Snow',
        subgroup: 'winter',
        image_type: 'scene',
        tags: [tag(9, 'weather', 'snow')],
      }),
      makeImage({ id: 4, name: 'Plain', subgroup: null, filename: 'plain.png' }),
    ]

    it('is hidden for a single-image group', async () => {
      setup(makeImage())
      await waitFor(() => expect(imageApi.getScenes).toHaveBeenCalled())
      expect(screen.queryByPlaceholderText('Filter…')).not.toBeInTheDocument()
    })

    it('partitions scenes by subgroup, with Other last', async () => {
      setup(scenes[0], scenes)
      await screen.findByPlaceholderText('Filter…')
      // The viewed image's own subgroup also appears in the metadata header
      const labels = ['summer', 'winter', 'Other'].map((l) => screen.getAllByText(l).slice(-1)[0])
      expect(labels[0].compareDocumentPosition(labels[1])).toBe(Node.DOCUMENT_POSITION_FOLLOWING)
      expect(labels[1].compareDocumentPosition(labels[2])).toBe(Node.DOCUMENT_POSITION_FOLLOWING)
      expect(screen.getAllByTestId('scene-tile')).toHaveLength(4)
    })

    it('filters by name, subgroup or filename stem and shows the count', async () => {
      const { user } = setup(scenes[0], scenes)
      const filter = await screen.findByPlaceholderText('Filter…')
      await user.type(filter, 'alt')
      expect(screen.getAllByTestId('scene-tile')).toHaveLength(1)
      expect(screen.getByText(/\(1\/4\s*\)/)).toBeInTheDocument()
      // A single section shows no subgroup headers
      expect(screen.getAllByText('summer')).toHaveLength(1)

      await user.clear(filter)
      await user.type(filter, 'winter')
      expect(screen.getAllByTestId('scene-tile')).toHaveLength(1)

      await user.clear(filter)
      await user.type(filter, 'png')
      expect(screen.getByText('No scenes match')).toBeInTheDocument()
    })

    it('offers a type toggle only for mixed groups', async () => {
      const { user } = setup(scenes[0], scenes)
      await screen.findByPlaceholderText('Filter…')
      await user.click(screen.getByRole('button', { name: 'Scenes' }))
      expect(screen.getAllByTestId('scene-tile')).toHaveLength(1)
      await user.click(screen.getByRole('button', { name: 'Maps' }))
      expect(screen.getAllByTestId('scene-tile')).toHaveLength(3)
    })

    it('has no type toggle when all scenes share a type', async () => {
      const same = scenes.map((s) => ({ ...s, image_type: 'battlemap' as const }))
      setup(same[0], same)
      await screen.findByPlaceholderText('Filter…')
      expect(screen.queryByRole('button', { name: 'Scenes' })).not.toBeInTheDocument()
    })

    it('applies and removes tag filters from the filter menu', async () => {
      const { user } = setup(scenes[0], scenes)
      await screen.findByPlaceholderText('Filter…')
      await user.click(screen.getByTitle('Filter scenes'))
      await user.click(await screen.findByTitle(/^snow — /))
      expect(screen.getAllByTestId('scene-tile')).toHaveLength(1)
      expect(screen.getByTestId('filter-chip')).toHaveTextContent('weather: snow')

      await user.click(within(screen.getByTestId('filter-chip')).getByTitle('Switch to exclude'))
      expect(screen.getAllByTestId('scene-tile')).toHaveLength(3)

      await user.click(within(screen.getByTestId('filter-chip')).getByTitle('Remove'))
      expect(screen.getAllByTestId('scene-tile')).toHaveLength(4)
    })

    it('disables the filter button when there is nothing to filter on', async () => {
      const plain = [makeImage({ id: 1 }), makeImage({ id: 2, name: 'Two' })]
      setup(plain[0], plain)
      await screen.findByPlaceholderText('Filter…')
      expect(screen.getByTitle('No filterable dimensions')).toBeDisabled()
    })

    it('switches image when a scene is clicked', async () => {
      const { user, onImageChange } = setup(scenes[0], scenes)
      await screen.findByPlaceholderText('Filter…')
      await user.click(screen.getByRole('button', { name: /Snow/ }))
      expect(onImageChange).toHaveBeenCalledWith(scenes[2])
    })
  })

  describe('delete', () => {
    it('moves to the nearest sibling after deleting', async () => {
      const scenes = [makeImage({ id: 1 }), makeImage({ id: 2, name: 'B' })]
      const { user, onImageChange, onDelete } = setup(scenes[0], scenes)
      await screen.findByPlaceholderText('Filter…')
      await user.click(screen.getByTitle('Delete image'))
      await user.click(
        within(screen.getByRole('dialog', { name: 'Delete Image' })).getByRole('button', {
          name: 'Delete',
        }),
      )
      await waitFor(() => expect(onImageChange).toHaveBeenCalledWith(scenes[1]))
      expect(imageApi.delete).toHaveBeenCalledWith(1)
      expect(onDelete).not.toHaveBeenCalled()
    })

    it('delegates to onDelete when no siblings remain', async () => {
      const { user, onDelete } = setup(makeImage())
      await waitFor(() => expect(imageApi.getScenes).toHaveBeenCalled())
      await user.click(screen.getByTitle('Delete image'))
      await user.click(
        within(screen.getByRole('dialog', { name: 'Delete Image' })).getByRole('button', {
          name: 'Delete',
        }),
      )
      await waitFor(() => expect(onDelete).toHaveBeenCalledWith(1))
    })
  })
})
