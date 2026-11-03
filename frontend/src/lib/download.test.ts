import { describe, it, expect, vi, afterEach } from 'vitest'
import { postForDownload, saveUrl } from './download'

describe('postForDownload', () => {
  afterEach(() => vi.restoreAllMocks())

  it('submits the fields as a hidden form and leaves nothing behind', () => {
    const submit = vi.spyOn(HTMLFormElement.prototype, 'submit').mockImplementation(() => {})
    postForDownload('/api/v1/downloads', { group_ids: '1,2', image_ids: '' })
    expect(submit).toHaveBeenCalledTimes(1)
    const form = submit.mock.contexts[0] as HTMLFormElement
    expect(form.method).toBe('post')
    expect(form.action).toMatch(/\/api\/v1\/downloads$/)
    expect(Object.fromEntries(new FormData(form))).toEqual({ group_ids: '1,2', image_ids: '' })
    expect(document.querySelector('form')).toBeNull()
  })
})

describe('saveUrl', () => {
  it('clicks a download link for the URL', () => {
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    saveUrl('/api/v1/images/3/file?download=1', '')
    expect(click).toHaveBeenCalledTimes(1)
    expect(document.querySelector('a')).toBeNull()
  })
})
