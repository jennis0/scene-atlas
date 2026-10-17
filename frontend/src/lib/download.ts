import axios, { type AxiosRequestConfig } from 'axios'

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
