import { describe, it, expect, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { useState } from 'react'
import { Dialog, DialogContent, DialogTitle } from './dialog'
import { PanelTitle } from './panel-title'
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
        <input aria-label="inline edit" onKeyDown={(e) => e.stopPropagation()} />
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

  it('leaves Escape to an open Radix menu or popover', () => {
    const onOuterChange = vi.fn()
    render(
      <>
        <Nested onOuterChange={onOuterChange} onInnerChange={vi.fn()} />
        <div data-radix-popper-content-wrapper="">
          <div data-state="open" role="menu" />
        </div>
      </>,
    )
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(onOuterChange).not.toHaveBeenCalled()
  })

  it('still closes when a menu is only animating out, even if it prevented default', () => {
    // Opening a dialog from a dropdown item leaves the menu mounted (closed) briefly.
    const onOuterChange = vi.fn()
    render(
      <>
        <Nested onOuterChange={onOuterChange} onInnerChange={vi.fn()} />
        <div data-radix-popper-content-wrapper="">
          <div data-state="closed" role="menu" />
        </div>
      </>,
    )
    const event = new KeyboardEvent('keydown', { key: 'Escape', cancelable: true })
    event.preventDefault()
    window.dispatchEvent(event)
    expect(onOuterChange).toHaveBeenCalledWith(false)
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

/** A page with an opener button in the app root, like the real app's #root. */
function Page({ children }: { children: (open: boolean, close: () => void) => React.ReactNode }) {
  const [open, setOpen] = useState(false)
  return (
    <div data-testid="app-root">
      <button onClick={() => setOpen(true)}>opener</button>
      {children(open, () => setOpen(false))}
    </div>
  )
}

describe('Dialog as a modal layer', () => {
  it('inerts the page beneath while open, and only while open', () => {
    render(
      <Page>
        {(open, close) => (
          <Dialog open={open} onOpenChange={(v) => !v && close()}>
            <DialogContent>
              <button onClick={close}>close</button>
            </DialogContent>
          </Dialog>
        )}
      </Page>,
    )
    // render() mounts into a container div that is itself a child of <body>
    const pageLayer = screen.getByTestId('app-root').parentElement!
    fireEvent.click(screen.getByText('opener'))
    expect(pageLayer).toHaveAttribute('inert')
    expect(screen.getByRole('dialog').closest('[inert]')).toBeNull()

    fireEvent.click(screen.getByText('close'))
    expect(pageLayer).not.toHaveAttribute('inert')
  })

  it('returns focus to the element that opened it', () => {
    render(
      <Page>
        {(open, close) => (
          <Dialog open={open} onOpenChange={(v) => !v && close()}>
            <DialogContent>
              <button onClick={close}>close</button>
            </DialogContent>
          </Dialog>
        )}
      </Page>,
    )
    const opener = screen.getByText('opener')
    opener.focus()
    fireEvent.click(opener)
    fireEvent.click(screen.getByText('close'))
    expect(opener).toHaveFocus()
  })

  it("returns focus to a menu's trigger when opened from a menu item", () => {
    function MenuPage() {
      const [open, setOpen] = useState(false)
      const [menu, setMenu] = useState(true)
      return (
        <>
          <button id="trigger">actions</button>
          {menu && (
            <div role="menu" aria-labelledby="trigger">
              <button role="menuitem" onClick={() => setOpen(true)}>
                edit
              </button>
            </div>
          )}
          <Dialog open={open} onOpenChange={setOpen}>
            <DialogContent>
              <button
                onClick={() => {
                  // Radix unmounts the menu after its close animation, by which
                  // time the dialog has opened; the focused item goes with it.
                  setMenu(false)
                  setOpen(false)
                }}
              >
                close
              </button>
            </DialogContent>
          </Dialog>
        </>
      )
    }
    render(<MenuPage />)
    const item = screen.getByRole('menuitem')
    item.focus()
    fireEvent.click(item)
    fireEvent.click(screen.getByText('close'))
    expect(screen.getByText('actions')).toHaveFocus()
  })

  it('leaves elements marked data-modal-exempt usable', () => {
    const exempt = document.createElement('div')
    exempt.setAttribute('data-modal-exempt', '')
    document.body.appendChild(exempt)
    render(
      <Dialog open onOpenChange={vi.fn()}>
        <DialogContent>x</DialogContent>
      </Dialog>,
    )
    expect(exempt).not.toHaveAttribute('inert')
    exempt.remove()
  })
})

describe('Dialog naming', () => {
  it('is named by a DialogTitle inside it', () => {
    render(
      <Dialog open onOpenChange={vi.fn()}>
        <DialogContent>
          <DialogTitle>Delete Image</DialogTitle>
        </DialogContent>
      </Dialog>,
    )
    expect(screen.getByRole('dialog', { name: 'Delete Image' })).toBeInTheDocument()
  })

  it('is named by a PanelTitle inside it', () => {
    render(
      <Dialog open onOpenChange={vi.fn()}>
        <DialogContent>
          <PanelTitle>Tag Management</PanelTitle>
        </DialogContent>
      </Dialog>,
    )
    expect(screen.getByRole('dialog', { name: 'Tag Management' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Tag Management' })).toBeInTheDocument()
  })

  it('prefers a name the caller gives it', () => {
    render(
      <Dialog open onOpenChange={vi.fn()}>
        <DialogContent aria-label="Edit group">
          <PanelTitle>Something else</PanelTitle>
        </DialogContent>
      </Dialog>,
    )
    expect(screen.getByRole('dialog', { name: 'Edit group' })).toBeInTheDocument()
  })
})
