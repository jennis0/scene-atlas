import { vi } from 'vitest'

/**
 * jsdom has no layout: every size is 0, so virtualised lists render no rows.
 * This gives every element a `width` x `height` box through all the size APIs a
 * library might read (offset*, client*, getBoundingClientRect), rather than
 * the one a given version happens to use: @tanstack/virtual-core 3.19.6 moved
 * from offsetHeight to clientHeight, and mocks of only offset* broke.
 *
 * Returns a function that restores the real (zero) sizes.
 */
export function fakeLayout({ width, height }: { width: number; height: number }): () => void {
  const box = { width, height, top: 0, left: 0, right: width, bottom: height, x: 0, y: 0 }
  const proto = HTMLElement.prototype
  const spies = [
    vi.spyOn(proto, 'offsetWidth', 'get').mockReturnValue(width),
    vi.spyOn(proto, 'offsetHeight', 'get').mockReturnValue(height),
    vi.spyOn(proto, 'clientWidth', 'get').mockReturnValue(width),
    vi.spyOn(proto, 'clientHeight', 'get').mockReturnValue(height),
    vi
      .spyOn(proto, 'getBoundingClientRect')
      .mockReturnValue({ ...box, toJSON: () => box } as DOMRect),
  ]
  return () => spies.forEach((spy) => spy.mockRestore())
}
