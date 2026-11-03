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

/** POST *fields* as a form whose attachment response the browser saves itself (a form,
 * not a fetch, so nothing is held in memory: design/export-backup-move.md §5.2). */
export function postForDownload(url: string, fields: Record<string, string>): void {
  const form = document.createElement('form')
  form.method = 'post'
  form.action = url
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
