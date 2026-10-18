import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '@/test/renderWithProviders'
import {
  counts,
  group,
  idleQueue,
  installFakeImportManager,
  item,
  jobDetail,
  jobSummary,
  uninstallFakeImportManager,
  type FakeImportClient,
} from '@/test/importFakes'
import type { ImportManager } from '@/lib/import/ImportManager'
import { toast } from 'sonner'
import { ImportDialog } from './ImportDialog'
import { isCleanFinish, jobStatusText, outcomeText, timeLeftText } from './format'

vi.mock('sonner', async (importOriginal) => {
  const actual = await importOriginal<typeof import('sonner')>()
  return { ...actual, toast: Object.assign(vi.fn(), actual.toast) }
})

let manager: ImportManager | undefined
let client: FakeImportClient
afterEach(() => {
  if (manager) uninstallFakeImportManager(manager)
  manager = undefined
})

const noop = () => {}

// jsdom has no layout; give elements a size so virtualised lists render rows.
const sizes: Array<ReturnType<typeof vi.spyOn>> = []
beforeAll(() => {
  sizes.push(vi.spyOn(HTMLElement.prototype, 'offsetHeight', 'get').mockReturnValue(480))
  sizes.push(vi.spyOn(HTMLElement.prototype, 'offsetWidth', 'get').mockReturnValue(640))
})
afterAll(() => sizes.forEach((spy) => spy.mockRestore()))

// ---------------------------------------------------------------------------
// Wording
// ---------------------------------------------------------------------------

describe('format', () => {
  it('summarises outcomes', () => {
    expect(outcomeText(counts({ done: 412, failed: 3, duplicate: 12 }))).toBe(
      '412 imported, 3 failed, 12 already in your library',
    )
  })

  it('estimates the time left from the measured time per file', () => {
    expect(timeLeftText(counts({ ready: 10 }), null)).toBeNull()
    expect(timeLeftText(counts({ done: 10 }), 2)).toBeNull() // nothing left
    expect(timeLeftText(counts({ ready: 20 }), 2)).toBe('under a minute left')
    expect(timeLeftText(counts({ ready: 200, awaiting_bytes: 100 }), 2)).toBe('about 10 min left')
    expect(timeLeftText(counts({ ready: 1000 }), 1.6)).toBe('about 25 min left') // 26.7 → 25
    expect(timeLeftText(counts({ processing: 16, ready: 4484 }), 2)).toBe('about 2 h 30 min left')
  })

  it('prefers what this tab is sending over server progress', () => {
    const job = jobSummary({ counts: counts({ awaiting_bytes: 5, done: 2 }) })
    const upload = {
      jobId: 'job1',
      label: 'x',
      phase: 'uploading' as const,
      totalFiles: 7,
      sentFiles: 2,
      skippedAsDuplicate: 0,
      totalBytes: 0,
      sentBytes: 0,
      failures: [],
      error: null,
    }
    expect(jobStatusText(job, upload)).toBe('Sending 2 of 7 files. 2 imported')
    expect(jobStatusText(job, undefined)).toBe('2 of 7 files processed')
  })
})

// ---------------------------------------------------------------------------
// Import dialog
// ---------------------------------------------------------------------------

describe('ImportDialog: start', () => {
  it('starts an import with the chosen type and hands over the job id', async () => {
    ;({ manager, client } = await installFakeImportManager())
    const onStarted = vi.fn()
    renderWithProviders(<ImportDialog jobId={null} open onClose={noop} onStarted={onStarted} />)
    await userEvent.click(screen.getByRole('button', { name: /Scenes/ }))
    const input = document.querySelector('input[type="file"][accept]') as HTMLInputElement
    const file = new File([new Uint8Array(4)], 'a.png')
    fireEvent.change(input, { target: { files: [file] } })

    await waitFor(() => expect(onStarted).toHaveBeenCalledWith('new-job'))
    expect(client.create).toHaveBeenCalledWith('a.png', 'scene')
  })
})

describe('ImportDialog: Auto', () => {
  it('starts on Auto and explains what it skips', async () => {
    ;({ manager, client } = await installFakeImportManager())
    renderWithProviders(<ImportDialog jobId={null} open onClose={noop} onStarted={noop} />)
    expect(screen.getByRole('button', { name: /Auto/ })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByText(/Tokens and other art are skipped/)).toBeInTheDocument()
  })
})

describe('ImportDialog: start in the desktop app', () => {
  const electron = (overrides = {}) => {
    window.electronAPI = {
      getPathForFile: (file: File) => `/maps/${file.name}`,
      chooseImportFolders: vi.fn(async () => ['/maps/Forest Pack']),
      chooseImportFiles: vi.fn(async () => []),
      ...overrides,
    } as unknown as NonNullable<Window['electronAPI']>
  }
  afterEach(() => {
    delete window.electronAPI
  })

  it('imports a chosen folder by path, without uploading', async () => {
    electron()
    ;({ manager, client } = await installFakeImportManager())
    const onStarted = vi.fn()
    renderWithProviders(<ImportDialog jobId={null} open onClose={noop} onStarted={onStarted} />)
    await userEvent.click(screen.getByRole('button', { name: /Choose a folder/ }))

    await waitFor(() => expect(onStarted).toHaveBeenCalledWith('new-job'))
    expect(client.create).toHaveBeenCalledWith('Forest Pack', 'auto')
    await waitFor(() =>
      expect(client.localSources).toHaveBeenCalledWith('new-job', ['/maps/Forest Pack']),
    )
    expect(client.manifest).not.toHaveBeenCalled()
  })

  it('does nothing when the picker is cancelled', async () => {
    electron({ chooseImportFolders: vi.fn(async () => []) })
    ;({ manager, client } = await installFakeImportManager())
    renderWithProviders(<ImportDialog jobId={null} open onClose={noop} onStarted={noop} />)
    await userEvent.click(screen.getByRole('button', { name: /Choose a folder/ }))
    expect(client.create).not.toHaveBeenCalled()
  })

  it('imports dropped folders by path', async () => {
    electron()
    ;({ manager, client } = await installFakeImportManager())
    renderWithProviders(<ImportDialog jobId={null} open onClose={noop} onStarted={noop} />)
    const zone = screen.getByText('Drop files or folders here')
    fireEvent.drop(zone, {
      dataTransfer: { files: [new File([], 'Forest'), new File([], 'Cave')] },
    })
    await waitFor(() =>
      expect(client.localSources).toHaveBeenCalledWith('new-job', ['/maps/Forest', '/maps/Cave']),
    )
    expect(client.create).toHaveBeenCalledWith('2 folders and files', 'auto')
  })
})

describe('ImportDialog: progress', () => {
  // Two import groups adding to one gallery group, 41
  const detail = (partial = {}) =>
    jobDetail({
      ...partial,
      groups: [group(), group({ id: 2, group_name: 'Swamp Hut', merged_into_existing: true })],
      reviewable_group_ids: [41],
    })

  it('shows overall progress, groups done, time left and the groups importing now', async () => {
    const running = counts({ done: 3, ready: 900 })
    ;({ manager, client } = await installFakeImportManager({
      jobs: [jobSummary({ counts: running, group_count: 347, groups_done: 103 })],
      queue: { ...idleQueue, seconds_per_item: 2 },
      details: {
        job1: jobDetail({
          groups: [
            group({ group_name: 'Forest Ponds', counts: counts({ done: 12, ready: 6 }) }),
            group({ id: 2, group_name: 'Frozen Lake', counts: counts({ awaiting_bytes: 4 }) }),
          ],
        }),
      },
    }))
    renderWithProviders(<ImportDialog jobId="job1" open onClose={noop} onStarted={noop} />)
    const now = await screen.findByRole('region', { name: 'Now importing' })
    const rows = within(now).getAllByRole('listitem')
    expect(rows[0]).toHaveTextContent('Forest Ponds')
    expect(rows[0]).toHaveTextContent('12/18')
    expect(rows[1]).toHaveTextContent('waiting')
    expect(screen.getByText('103 of 347 groups done · about 30 min left')).toBeInTheDocument()
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '3')
    expect(client.get).toHaveBeenCalledWith('job1', 'active')
  })

  it('pauses and cancels from the footer, and says the import carries on once closed', async () => {
    const onClose = vi.fn()
    ;({ manager, client } = await installFakeImportManager({
      jobs: [jobSummary({ counts: counts({ ready: 5 }) })],
      details: { job1: detail() },
    }))
    renderWithProviders(<ImportDialog jobId="job1" open onClose={onClose} onStarted={noop} />)
    await userEvent.click(await screen.findByRole('button', { name: 'Pause' }))
    expect(client.action).toHaveBeenCalledWith('job1', 'pause')
    expect(screen.getByRole('button', { name: 'Cancel import' })).toBeInTheDocument()

    await userEvent.click(screen.getAllByRole('button', { name: 'Close' })[1])
    expect(onClose).toHaveBeenCalled()
    expect(toast).toHaveBeenCalledWith('Forest Pack is still importing', expect.anything())
  })

  it('counts a group against what it could import, not files already in the library', async () => {
    const partly = group({ counts: counts({ done: 3, duplicate: 3, skipped: 1, ready: 2 }) })
    ;({ manager, client } = await installFakeImportManager({
      jobs: [jobSummary({ counts: partly.counts })],
      details: { job1: jobDetail({ groups: [partly] }) },
    }))
    renderWithProviders(<ImportDialog jobId="job1" open onClose={noop} onStarted={noop} />)
    const row = await screen.findByRole('listitem')
    expect(row).toHaveTextContent('3/5')
  })

  it('sums up problems in one line while importing', async () => {
    ;({ manager, client } = await installFakeImportManager({
      jobs: [jobSummary({ counts: counts({ ready: 5, duplicate: 98, failed: 3 }) })],
      details: { job1: detail() },
    }))
    renderWithProviders(<ImportDialog jobId="job1" open onClose={noop} onStarted={noop} />)
    expect(await screen.findByText(/98 already in your library/)).toHaveTextContent(
      '98 already in your library · 3 failed. The report lists them when the import finishes.',
    )
  })

  it('reviews the groups imported so far', async () => {
    const onReviewGroups = vi.fn()
    ;({ manager, client } = await installFakeImportManager({
      jobs: [jobSummary({ counts: counts({ ready: 5, done: 6 }), groups_reviewable: 2 })],
      details: {
        job1: detail({ counts: counts({ ready: 5, done: 6 }) }),
      },
    }))
    renderWithProviders(
      <ImportDialog
        jobId="job1"
        open
        onClose={noop}
        onStarted={noop}
        onReviewGroups={onReviewGroups}
      />,
    )
    await userEvent.click(await screen.findByRole('button', { name: 'Review 2 groups' }))
    await waitFor(() => expect(onReviewGroups).toHaveBeenCalledWith([41])) // as the server says
  })

  it('offers no review before any group has images', async () => {
    ;({ manager, client } = await installFakeImportManager({
      jobs: [jobSummary({ counts: counts({ ready: 5 }) })],
      details: { job1: detail() },
    }))
    renderWithProviders(
      <ImportDialog jobId="job1" open onClose={noop} onStarted={noop} onReviewGroups={vi.fn()} />,
    )
    await screen.findByRole('button', { name: 'Cancel import' })
    expect(screen.queryByRole('button', { name: /^Review/ })).not.toBeInTheDocument()
  })

  it('offers resume or finishing without missing files after an interrupted upload', async () => {
    ;({ manager, client } = await installFakeImportManager({
      jobs: [
        jobSummary({ upload_interrupted: true, counts: counts({ awaiting_bytes: 7, done: 3 }) }),
      ],
      details: { job1: detail() },
    }))
    renderWithProviders(<ImportDialog jobId="job1" open onClose={noop} onStarted={noop} />)
    expect(screen.getByText(/still to send/)).toHaveTextContent('7 files')
    await userEvent.click(screen.getByText('Finish without them'))
    expect(client.action).toHaveBeenCalledWith('job1', 'finish-upload')
  })

  it('says which folder a local import is waiting for', async () => {
    ;({ manager, client } = await installFakeImportManager({
      jobs: [jobSummary({ local: true, waiting_for: ['D:\\Maps'], counts: counts({ ready: 4 }) })],
      details: { job1: detail() },
    }))
    renderWithProviders(<ImportDialog jobId="job1" open onClose={noop} onStarted={noop} />)
    expect(screen.getByText(/Can't find D:\\Maps/)).toBeInTheDocument()
    expect(screen.getByText('Waiting for D:\\Maps')).toBeInTheDocument()
  })

  it('explains a system pause', async () => {
    ;({ manager, client } = await installFakeImportManager({
      jobs: [jobSummary({ counts: counts({ ready: 1 }) })],
      queue: { ...idleQueue, system_paused: true, reason: 'No AI model is available' },
    }))
    renderWithProviders(<ImportDialog jobId="job1" open onClose={noop} onStarted={noop} />)
    expect(screen.getByText(/Importing is paused: No AI model is available/)).toBeInTheDocument()
  })

  it('confirms before cancelling and says finished images stay', async () => {
    ;({ manager, client } = await installFakeImportManager({
      jobs: [jobSummary({ counts: counts({ ready: 2, done: 3 }) })],
    }))
    renderWithProviders(<ImportDialog jobId="job1" open onClose={noop} onStarted={noop} />)
    await userEvent.click(screen.getByText('Cancel import'))
    expect(screen.getByRole('alertdialog')).toHaveTextContent('3 images already imported stay')
    await userEvent.click(
      within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Cancel import' }),
    )
    await waitFor(() => expect(client.action).toHaveBeenCalledWith('job1', 'cancel'))
  })

  it('turns into the result once the import finishes', async () => {
    ;({ manager, client } = await installFakeImportManager({
      jobs: [jobSummary({ status: 'completed', counts: counts({ done: 5, failed: 1 }) })],
    }))
    renderWithProviders(<ImportDialog jobId="job1" open onClose={noop} onStarted={noop} />)
    expect(screen.getByText(/5 imported, 1 failed/)).toBeInTheDocument()
    expect(screen.queryByText('Cancel import')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Undo import' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Done' })).toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// Report
// ---------------------------------------------------------------------------

describe('ImportDialog: result', () => {
  const finished = jobSummary({
    status: 'completed',
    counts: counts({ done: 5, failed: 2, duplicate: 1 }),
    group_count: 1,
  })

  async function setup() {
    ;({ manager, client } = await installFakeImportManager({
      jobs: [finished],
      details: { job1: jobDetail({ ...finished, groups: [group()], reviewable_group_ids: [41] }) },
      items: [
        item({ id: 10 }),
        item({ id: 11, relative_path: 'P/b.png', error_reason: 'File was not found' }),
        item({
          id: 12,
          state: 'duplicate',
          relative_path: 'P/c.png',
          duplicate_of_image_id: 99,
          duplicate_tier: 'bytes',
          error_reason: null,
        }),
      ],
    }))
  }

  it('only shows sections that have entries', async () => {
    await setup()
    renderWithProviders(<ImportDialog onStarted={noop} jobId="job1" open onClose={noop} />)
    const tabs = screen.getAllByRole('tab').map((t) => t.textContent)
    expect(tabs).toEqual(['Groups1', 'Problems2', 'Already in library1'])
  })

  it('groups problems by reason and retries a group of them', async () => {
    await setup()
    renderWithProviders(<ImportDialog onStarted={noop} jobId="job1" open onClose={noop} />)
    await userEvent.click(screen.getByRole('tab', { name: /Problems/ }))
    await waitFor(() => expect(screen.getByText('File was not found')).toBeInTheDocument())
    expect(screen.getByText('Image is corrupt or not a supported format')).toBeInTheDocument()
    await userEvent.click(screen.getAllByText('Retry')[0])
    expect(client.itemAction).toHaveBeenCalledWith('job1', 'retry', [10])
  })

  it('imports duplicates as new copies', async () => {
    await setup()
    renderWithProviders(<ImportDialog onStarted={noop} jobId="job1" open onClose={noop} />)
    await userEvent.click(screen.getByRole('tab', { name: /Already in library/ }))
    await waitFor(() => expect(screen.getByText('P/c.png')).toBeInTheDocument())
    await userEvent.click(screen.getByText('Import as new copies'))
    expect(client.itemAction).toHaveBeenCalledWith('job1', 'import-as-copy', [12])
  })

  it('opens the groups it created in the editor', async () => {
    await setup()
    const onReviewGroups = vi.fn()
    renderWithProviders(
      <ImportDialog
        onStarted={noop}
        jobId="job1"
        open
        onClose={noop}
        onReviewGroups={onReviewGroups}
      />,
    )
    await waitFor(() => expect(screen.getByText('Review in editor')).toBeInTheDocument())
    await userEvent.click(screen.getByText('Review in editor'))
    expect(onReviewGroups).toHaveBeenCalledWith([41])
  })

  it('undoes only after confirmation', async () => {
    await setup()
    const onUndone = vi.fn()
    const onClose = vi.fn()
    renderWithProviders(
      <ImportDialog onStarted={noop} jobId="job1" open onClose={onClose} onUndone={onUndone} />,
    )
    await userEvent.click(screen.getByText('Undo import'))
    expect(client.undo).not.toHaveBeenCalled()
    expect(screen.getByRole('alertdialog')).toHaveTextContent('deletes the 5 images')
    await userEvent.click(screen.getByRole('button', { name: 'Delete imported images' }))
    await waitFor(() => expect(client.undo).toHaveBeenCalledWith('job1'))
    expect(onUndone).toHaveBeenCalled()
    expect(onClose).toHaveBeenCalled()
  })

  it('closes with Done, clearing a finished import from the activity list', async () => {
    await setup()
    const onClose = vi.fn()
    renderWithProviders(<ImportDialog onStarted={noop} jobId="job1" open onClose={onClose} />)
    await userEvent.click(screen.getByRole('button', { name: 'Done' }))
    await waitFor(() => expect(client.action).toHaveBeenCalledWith('job1', 'dismiss'))
    expect(onClose).toHaveBeenCalled()
  })

  it('opens on the problems when some files failed', async () => {
    await setup()
    renderWithProviders(<ImportDialog onStarted={noop} jobId="job1" open onClose={noop} />)
    await waitFor(() =>
      expect(screen.getByRole('tab', { name: /Problems/ })).toHaveAttribute(
        'aria-selected',
        'true',
      ),
    )
  })

  it('opens the editor on a group when the group is clicked', async () => {
    await setup()
    const onReviewGroups = vi.fn()
    renderWithProviders(
      <ImportDialog
        onStarted={noop}
        jobId="job1"
        open
        onClose={noop}
        onReviewGroups={onReviewGroups}
      />,
    )
    await userEvent.click(screen.getByRole('tab', { name: /Groups/ }))
    await userEvent.click(await screen.findByText('Island Fort'))
    expect(onReviewGroups).toHaveBeenCalledWith([41], 41)
  })

  it('names the shared author once instead of on every group', async () => {
    await setup()
    renderWithProviders(<ImportDialog onStarted={noop} jobId="job1" open onClose={noop} />)
    await userEvent.click(screen.getByRole('tab', { name: /Groups/ }))
    await screen.findByText('Island Fort')
    expect(screen.getByText(/· Czepeku$/)).toBeInTheDocument()
    expect(screen.queryByText('Czepeku', { exact: true })).not.toBeInTheDocument()
  })
})

describe('ImportDialog: result, skipped by Auto', () => {
  const skipped = (partial: Partial<ReturnType<typeof item>>) =>
    item({ state: 'skipped', error_reason: 'Looks like a token', ...partial })

  async function setup(items: ReturnType<typeof item>[], sortedOut: number) {
    const finished = jobSummary({
      status: 'completed',
      counts: counts({ done: 1, skipped: items.length, sorted_out: sortedOut }),
    })
    ;({ manager, client } = await installFakeImportManager({
      jobs: [finished],
      details: { job1: jobDetail({ ...finished, groups: [group()], reviewable_group_ids: [41] }) },
      items,
    }))
    renderWithProviders(<ImportDialog onStarted={noop} jobId="job1" open onClose={noop} />)
  }

  it('opens on Skipped, shows previews and includes a reason group, but not other skips', async () => {
    const success = vi.spyOn(toast, 'success')
    await setup(
      [
        skipped({
          id: 20,
          error_kind: 'sorted_out',
          relative_path: 'P/goblin.png',
          has_preview: true,
        }),
        skipped({
          id: 21,
          error_kind: 'sorted_out',
          relative_path: 'P/orc.png',
          has_preview: true,
        }),
        skipped({
          id: 22,
          error_kind: null,
          error_reason: 'Not a supported image, video or archive',
          relative_path: 'P/readme.txt',
        }),
      ],
      2,
    )
    expect(screen.getByRole('tab', { name: /Skipped/ })).toHaveAttribute('aria-selected', 'true')
    await waitFor(() => expect(screen.getByText('P/goblin.png')).toBeInTheDocument())
    const previews = document.querySelectorAll('img[src*="/preview"]')
    expect([...previews].map((img) => img.getAttribute('src'))).toEqual([
      '/api/v1/imports/job1/items/20/preview',
      '/api/v1/imports/job1/items/21/preview',
    ])
    expect(screen.getAllByRole('button', { name: 'Include' })).toHaveLength(1)
    await userEvent.click(screen.getByRole('button', { name: 'Include' }))
    expect(client.include).toHaveBeenCalledWith([20, 21])
    await waitFor(() => expect(success).toHaveBeenCalledWith('Importing 2 images'))
    success.mockRestore()
  })

  it('offers no Include and no preview once they have expired', async () => {
    await setup(
      [
        skipped({ id: 20, error_kind: 'sorted_out_expired', relative_path: 'P/goblin.png' }),
        skipped({ id: 21, error_kind: 'sorted_out_expired', relative_path: 'P/orc.png' }),
      ],
      0,
    )
    await userEvent.click(screen.getByRole('tab', { name: /Skipped/ }))
    await waitFor(() => expect(screen.getByText('P/goblin.png')).toBeInTheDocument())
    expect(screen.getByText('Looks like a token')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Include' })).not.toBeInTheDocument()
    expect(document.querySelector('img[src*="/preview"]')).toBeNull()
  })
})

describe('isCleanFinish', () => {
  it('is not clean when Auto skipped files: a fully skipped group is only in the report', () => {
    const job = (c: Partial<Parameters<typeof counts>[0]>) =>
      jobSummary({ status: 'completed', counts: counts(c) })
    expect(isCleanFinish(job({ done: 3 }))).toBe(true)
    expect(isCleanFinish(job({ done: 3, skipped: 1, sorted_out: 1 }))).toBe(false)
    expect(isCleanFinish(job({ done: 3, skipped: 1 }))).toBe(true) // e.g. a readme.txt
  })
})

describe('ImportDialog: result, groups by type', () => {
  it('shows each group as maps, scenes and Auto skips', async () => {
    const finished = jobSummary({ status: 'completed', counts: counts({ done: 16, skipped: 3 }) })
    ;({ manager, client } = await installFakeImportManager({
      jobs: [finished],
      details: {
        job1: {
          ...finished,
          reviewable_group_ids: [41],
          groups: [
            group({
              map_count: 14,
              scene_count: 2,
              counts: counts({ done: 16, skipped: 3, sorted_out: 3 }),
            }),
          ],
        },
      },
    }))
    renderWithProviders(<ImportDialog onStarted={noop} jobId="job1" open onClose={noop} />)
    expect(await screen.findByTitle('14 maps, 2 scenes, 3 skipped by Auto')).toBeInTheDocument()
  })
})
