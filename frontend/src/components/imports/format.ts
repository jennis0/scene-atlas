/**
 * Wording and number formatting shared by the import dialog, dock and report.
 * One place for the vocabulary, so an action keeps its name across the flow.
 */

import type { LocalUpload } from '@/lib/import/ImportManager'
import type { ImportCounts, ImportGroupSummary, ImportJobSummary } from '@/lib/import/types'

export const plural = (n: number, one: string, many = `${one}s`) =>
  `${n.toLocaleString()} ${n === 1 ? one : many}`

export { formatBytes } from '@/lib/format'

/** Files that have reached a final state. */
export const finishedCount = (c: ImportCounts) => c.done + c.duplicate + c.failed + c.skipped

/** 0–1 progress of processing, over files that will be (or were) processed. */
export function processedRatio(c: ImportCounts): number {
  return c.total > 0 ? finishedCount(c) / c.total : 0
}

export const isFinished = (job: ImportJobSummary) =>
  job.status === 'completed' || job.status === 'cancelled'

/** What this tab is doing for the job right now, or null when it isn't sending anything. */
/**
 * A finished import with nothing to look at but its groups: completed, every file
 * imported or skipped (no failures, no files already in the library), and the
 * upload not cut short. Opening one goes straight to the editor.
 */
export const isCleanFinish = (job: ImportJobSummary) =>
  job.status === 'completed' &&
  job.counts.done > 0 &&
  job.counts.failed === 0 &&
  job.counts.duplicate === 0 &&
  !job.upload_interrupted

/** The image groups an import has added images to, for opening in the editor. */
export const reviewableGroupIds = (groups: ImportGroupSummary[]) =>
  groups.filter((g) => g.image_group_id !== null && g.counts.done > 0).map((g) => g.image_group_id!)

export function uploadPhaseText(upload: LocalUpload | undefined): string | null {
  if (!upload) return null
  switch (upload.phase) {
    case 'describing':
      return 'Reading the file list'
    case 'archives':
      return 'Unpacking archives'
    case 'sealing':
      return 'Sorting files into groups'
    case 'uploading':
      return `Sending ${upload.sentFiles.toLocaleString()} of ${plural(upload.totalFiles, 'file')}`
    case 'waiting-for-connection':
      return 'Waiting for the connection to come back'
    default:
      return null
  }
}

/** One-line outcome, e.g. "412 imported, 3 failed, 12 already in your library". */
export function outcomeText(c: ImportCounts): string {
  const parts = [`${c.done.toLocaleString()} imported`]
  if (c.failed) parts.push(`${c.failed.toLocaleString()} failed`)
  if (c.duplicate) parts.push(`${c.duplicate.toLocaleString()} already in your library`)
  return parts.join(', ')
}

/** Short status line for a job row (dock) or dialog header. */
export function jobStatusText(job: ImportJobSummary, upload: LocalUpload | undefined): string {
  const sending = uploadPhaseText(upload)
  if (sending && !isFinished(job)) {
    return job.counts.done > 0
      ? `${sending}. ${job.counts.done.toLocaleString()} imported`
      : sending
  }
  if (job.upload_interrupted) return 'Upload interrupted'
  if (job.status === 'paused') return `Paused. ${outcomeText(job.counts)}`
  if (job.status === 'cancelled') return `Cancelled. ${outcomeText(job.counts)}`
  if (job.status === 'completed') return outcomeText(job.counts)
  if (!job.planned) return 'Preparing'
  return `${finishedCount(job.counts).toLocaleString()} of ${plural(job.counts.total, 'file')} processed`
}
