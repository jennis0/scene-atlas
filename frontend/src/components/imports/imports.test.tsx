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
  jobSummary,
  uninstallFakeImportManager,
  type FakeImportClient,
} from '@/test/importFakes'
import type { ImportManager } from '@/lib/import/ImportManager'
import { ImportDialog } from './ImportDialog'
import { jobStatusText, outcomeText } from './format'

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
    expect(client.create).toHaveBeenCalledWith('Forest Pack', 'battlemap')
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
    expect(client.create).toHaveBeenCalledWith('2 folders and files', 'battlemap')
  })
})

describe('ImportDialog: progress', () => {
  const detail = (partial = {}) => ({
    ...jobSummary(partial),
    groups: [group(), group({ id: 2, group_name: 'Swamp Hut', merged_into_existing: true })],
  })

  it('shows the group ledger and overall progress', async () => {
    ;({ manager, client } = await installFakeImportManager({
      jobs: [jobSummary({ counts: counts({ ready: 2, done: 3 }) })],
      details: { job1: detail({ counts: counts({ ready: 2, done: 3 }) }) },
    }))
    renderWithProviders(<ImportDialog jobId="job1" open onClose={noop} onStarted={noop} />)
    await waitFor(() => expect(screen.getByText('Island Fort')).toBeInTheDocument())
    expect(screen.getByText(/adds to an existing group/)).toBeInTheDocument()
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '3')
    expect(screen.getByText('Keeps running if you close this')).toBeInTheDocument()
  })

  it('counts a group against what it could import, not files already in the library', async () => {
    // A settled group in a job that's still running other groups
    const settled = group({ counts: counts({ done: 3, duplicate: 3, skipped: 1 }) })
    ;({ manager, client } = await installFakeImportManager({
      jobs: [jobSummary({ counts: counts({ ...settled.counts, processing: 2 }) })],
      details: { job1: { ...jobSummary(), groups: [settled] } },
    }))
    renderWithProviders(<ImportDialog jobId="job1" open onClose={noop} onStarted={noop} />)
    const row = await screen.findByRole('listitem')
    expect(row).toHaveTextContent('3 in library')
    expect(row).toHaveTextContent('3/3')
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
      details: { job1: { ...finished, groups: [group()] } },
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
