/**
 * Wording and number formatting shared by the import dialog, dock and report.
 * One place for the vocabulary, so an action keeps its name across the flow.
 */

import type { LocalUpload } from '@/lib/import/ImportManager'
import type { ImportCounts, ImportJobSummary } from '@/lib/import/types'

export const plural = (n: number, one: string, many = `${one}s`) =>
  `${n.toLocaleString()} ${n === 1 ? one : many}`

export { formatBytes } from '@/lib/format'

/** Files that have reached a final state. */
export const finishedCount = (c: ImportCounts) => c.done + c.duplicate + c.failed + c.skipped

/** 0–1 progress of processing, over files that will be (or were) processed. */
export function processedRatio(c: ImportCounts): number {
  return c.total > 0 ? finishedCount(c) / c.total : 0
}

/** Files still to import: waiting for bytes, ready or being processed. */
export const openCount = (c: ImportCounts) => c.awaiting_bytes + c.ready + c.processing

/**
 * "about 25 min left", from the measured time to import one file (design/import-progress.md
 * §4) times the files left. Null until there's a rate, or when nothing is left. Long waits
 * are rounded to five minutes so the estimate doesn't flicker.
 */
export function timeLeftText(c: ImportCounts, secondsPerItem: number | null | undefined) {
  const open = openCount(c)
  if (!secondsPerItem || open === 0) return null
  const exact = (open * secondsPerItem) / 60
  if (exact < 1) return 'under a minute left'
  const minutes = exact < 15 ? Math.round(exact) : Math.round(exact / 5) * 5
  if (minutes < 60) return `about ${minutes} min left`
  const hours = Math.floor(minutes / 60)
  const rest = minutes % 60
  return rest ? `about ${hours} h ${rest} min left` : `about ${hours} h left`
}

export const isFinished = (job: ImportJobSummary) =>
  job.status === 'completed' || job.status === 'cancelled'

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
  !job.counts.sorted_out && // a group Auto skipped entirely is only in the report
  !job.upload_interrupted

/** What this tab is doing for the job right now, or null when it isn't sending anything. */
export function uploadPhaseText(upload: LocalUpload | undefined): string | null {
  if (!upload) return null
  switch (upload.phase) {
    case 'reading':
      return 'Reading the folders'
    case 'describing':
      return 'Reading the file list'
    case 'archives':
      return 'Unpacking archives'
    case 'sealing':
      return 'Reading the file names'
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
/** Why an open job isn't moving, if it's waiting on the user. */
function blockedText(job: ImportJobSummary): string | null {
  if (job.waiting_for.length && !isFinished(job)) return `Waiting for ${job.waiting_for[0]}`
  if (job.upload_interrupted) return 'Upload interrupted'
  return null
}

export function jobStatusText(job: ImportJobSummary, upload: LocalUpload | undefined): string {
  const sending = uploadPhaseText(upload)
  if (sending && !isFinished(job)) {
    return job.counts.done > 0
      ? `${sending}. ${job.counts.done.toLocaleString()} imported`
      : sending
  }
  const blocked = blockedText(job)
  if (blocked) return blocked
  if (job.status === 'paused') return `Paused. ${outcomeText(job.counts)}`
  if (job.status === 'cancelled') return `Cancelled. ${outcomeText(job.counts)}`
  if (job.status === 'completed') return outcomeText(job.counts)
  if (job.status === 'grouping') return 'Identifying groups'
  if (!job.planned) return 'Preparing'
  return `${finishedCount(job.counts).toLocaleString()} of ${plural(job.counts.total, 'file')} processed`
}
