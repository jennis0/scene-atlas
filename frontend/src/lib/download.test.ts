import { describe, it, expect, vi, afterEach } from 'vitest'
import { postForDownload, saveUrl } from './download'

describe('postForDownload', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    document.body.innerHTML = ''
  })

  it('submits the fields into a hidden frame of its own, and leaves no form behind', () => {
    const submit = vi.spyOn(HTMLFormElement.prototype, 'submit').mockImplementation(() => {})
    postForDownload('/api/v1/downloads', { group_ids: '1,2', image_ids: '' })
    expect(submit).toHaveBeenCalledTimes(1)
    const form = submit.mock.contexts[0] as HTMLFormElement
    expect(form.method).toBe('post')
    expect(form.action).toMatch(/\/api\/v1\/downloads$/)
    expect(Object.fromEntries(new FormData(form))).toEqual({ group_ids: '1,2', image_ids: '' })
    const frame = document.querySelector('iframe')
    expect(frame?.hidden).toBe(true)
    expect(form.target).toBe(frame?.name)
    expect(document.querySelector('form')).toBeNull()
    postForDownload('/api/v1/downloads', {})
    expect(document.querySelectorAll('iframe')).toHaveLength(1) // one frame, reused
  })

  it('passes an error that loads into the frame to onError, and nothing for a download', () => {
    vi.spyOn(HTMLFormElement.prototype, 'submit').mockImplementation(() => {})
    const onError = vi.fn()
    postForDownload('/api/v1/downloads', {}, onError)
    const frame = document.querySelector('iframe')!
    frame.dispatchEvent(new Event('load')) // an empty frame: a download, or nothing yet
    expect(onError).not.toHaveBeenCalled()
    frame.contentDocument!.body.textContent = "That's 1,200 images; download at most 999"
    frame.dispatchEvent(new Event('load'))
    expect(onError).toHaveBeenCalledWith("That's 1,200 images; download at most 999")
    // Read once: a later load doesn't repeat it
    frame.dispatchEvent(new Event('load'))
    expect(onError).toHaveBeenCalledTimes(1)
  })

  it("reports a page it can't read as a download that didn't start", () => {
    vi.spyOn(HTMLFormElement.prototype, 'submit').mockImplementation(() => {})
    const onError = vi.fn()
    postForDownload('/api/v1/downloads', {}, onError)
    const frame = document.querySelector('iframe')!
    Object.defineProperty(frame, 'contentDocument', {
      get: () => {
        throw new DOMException('Blocked a frame from accessing a cross-origin frame')
      },
    })
    frame.dispatchEvent(new Event('load'))
    expect(onError).toHaveBeenCalledWith(expect.stringContaining("didn't start"))
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
