import axios, { type AxiosRequestConfig } from 'axios'
import type { Image } from '@/types'

/**
 * Fetches `url` as a blob and saves it via a temporary <a download>. Fetching first
 * (rather than linking straight to the URL) lets callers show a busy state and toast
 * on failure instead of the browser navigating to an error response.
 */
export async function downloadFile(
  url: string,
  filename: string,
  axiosOpts?: AxiosRequestConfig,
): Promise<void> {
  const resp = await axios.get<Blob>(url, { ...axiosOpts, responseType: 'blob' })
  const objectUrl = URL.createObjectURL(resp.data)
  const a = document.createElement('a')
  a.href = objectUrl
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(objectUrl)
}

const sanitizeSegment = (s: string) =>
  s
    .replace(/[/\\:*?"<>|]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()

/** "Group - Subgroup - Name - Grid 20x15.ext", so downloaded files sort and read well. */
export function imageDownloadFilename(img: Image): string {
  const parts: string[] = []
  if (img.group_name && img.group_name !== img.name) parts.push(sanitizeSegment(img.group_name))
  if (img.subgroup) parts.push(sanitizeSegment(img.subgroup))
  parts.push(sanitizeSegment(img.name))

  if (img.gridded === true) {
    const label = img.grid_type === 'hex' ? 'Hex' : 'Grid'
    const dims = img.grid_width && img.grid_height ? ` ${img.grid_width}x${img.grid_height}` : ''
    parts.push(`${label}${dims}`)
  } else {
    parts.push('No Grid')
  }

  // The stored file's extension, which differs from the upload's after conversion.
  const ext = (img.storage_key || img.filename).match(/\.[^.]+$/)?.[0] ?? ''
  return parts.join(' - ') + ext
}
