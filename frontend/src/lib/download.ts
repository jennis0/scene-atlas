/** Let the browser download *url* itself, streaming to disk. The response must be an
 * attachment, or the page would navigate to it. An empty *filename* takes the server's. */
export function saveUrl(url: string, filename: string): void {
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
}

const DOWNLOAD_FRAME = 'scene-atlas-download'

function downloadFrame(): HTMLIFrameElement {
  const found = document.querySelector<HTMLIFrameElement>(`iframe[name="${DOWNLOAD_FRAME}"]`)
  if (found) return found
  const frame = document.createElement('iframe')
  frame.name = DOWNLOAD_FRAME
  frame.title = 'Downloads'
  frame.hidden = true
  document.body.appendChild(frame)
  return frame
}

/**
 * POST *fields* as a form whose attachment response the browser saves itself: a form,
 * not a fetch, so nothing is held in memory (design/export-backup-move.md §5.2).
 *
 * It's submitted into a hidden frame of the app's own, so a response that isn't a download
 * can't replace the app. A download leaves the frame as it was; an error loads into it as
 * plain text (the endpoint lets this frame show it), which goes to *onError*, as does a
 * page the app can't read (the request didn't reach the server).
 */
export function postForDownload(
  url: string,
  fields: Record<string, string>,
  onError?: (message: string) => void,
): void {
  const frame = downloadFrame()
  frame.onload = () => {
    let message: string
    try {
      const body = frame.contentDocument?.body
      message = body?.textContent?.trim() ?? ''
      if (body) body.textContent = '' // so a later load can't show it again
    } catch {
      // A page the app can't read (the browser's own error page, a proxy's): the request
      // never reached the endpoint
      message = "The download didn't start. Check the connection and try again."
    }
    if (message) onError?.(message)
  }
  const form = document.createElement('form')
  form.method = 'post'
  form.action = url
  form.target = DOWNLOAD_FRAME
  form.hidden = true
  for (const [name, value] of Object.entries(fields)) {
    const input = document.createElement('input')
    input.type = 'hidden'
    input.name = name
    input.value = value
    form.appendChild(input)
  }
  document.body.appendChild(form)
  form.submit()
  document.body.removeChild(form)
}
