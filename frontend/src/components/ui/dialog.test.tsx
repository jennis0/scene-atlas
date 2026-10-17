import { describe, it, expect, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { useState } from 'react'
import { Dialog, DialogContent } from './dialog'
import { isAnyDialogOpen } from './dialogStack'

function Nested({
  onOuterChange,
  onInnerChange,
}: {
  onOuterChange: (v: boolean) => void
  onInnerChange: (v: boolean) => void
}) {
  const [innerOpen, setInnerOpen] = useState(false)
  return (
    // Inline handlers: a new function each render, as most callers pass.
    <Dialog open onOpenChange={(v) => onOuterChange(v)}>
      <DialogContent>
        <button onClick={() => setInnerOpen(true)}>open inner</button>
        <input aria-label="inline edit" onKeyDown={(e) => e.preventDefault()} />
        <Dialog
          open={innerOpen}
          onOpenChange={(v) => {
            onInnerChange(v)
            setInnerOpen(v)
          }}
        >
          <DialogContent>inner</DialogContent>
        </Dialog>
      </DialogContent>
    </Dialog>
  )
}

describe('Dialog Escape handling', () => {
  it('closes only the topmost dialog', () => {
    const onOuterChange = vi.fn()
    const onInnerChange = vi.fn()
    render(<Nested onOuterChange={onOuterChange} onInnerChange={onInnerChange} />)
    fireEvent.click(screen.getByText('open inner'))
    expect(screen.getByText('inner')).toBeInTheDocument()

    fireEvent.keyDown(window, { key: 'Escape' })
    expect(onInnerChange).toHaveBeenCalledWith(false)
    expect(onOuterChange).not.toHaveBeenCalled()
    expect(screen.queryByText('inner')).not.toBeInTheDocument()

    fireEvent.keyDown(window, { key: 'Escape' })
    expect(onOuterChange).toHaveBeenCalledWith(false)
  })

  it('ignores an Escape that something inside already handled', () => {
    const onOuterChange = vi.fn()
    render(<Nested onOuterChange={onOuterChange} onInnerChange={vi.fn()} />)
    fireEvent.keyDown(screen.getByLabelText('inline edit'), { key: 'Escape' })
    expect(onOuterChange).not.toHaveBeenCalled()
  })

  it('unregisters when closed or unmounted', () => {
    const { rerender, unmount } = render(
      <Dialog open onOpenChange={vi.fn()}>
        <DialogContent>x</DialogContent>
      </Dialog>,
    )
    expect(isAnyDialogOpen()).toBe(true)
    rerender(
      <Dialog open={false} onOpenChange={vi.fn()}>
        <DialogContent>x</DialogContent>
      </Dialog>,
    )
    expect(isAnyDialogOpen()).toBe(false)
    unmount()
    expect(isAnyDialogOpen()).toBe(false)
  })
})
