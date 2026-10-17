# Dialog Focus Management

## Problem: Focus loss when opening dialogs from Radix dropdowns

When a custom `Dialog` opens in response to a Radix UI `DropdownMenu` item click, the dialog's search input (or other autofocus target) loses focus immediately after receiving it.

### Root causes (two independent issues)

**1. Radix DropdownMenu content steals focus during close**

When a `DropdownMenuItem` is clicked, Radix's close sequence briefly moves focus to the dropdown's content element (~6ms after our dialog focuses its target). This happens during the dropdown's unmount/animation, before the content is fully removed from the DOM.

`onCloseAutoFocus={(e) => e.preventDefault()}` on `DropdownMenuContent` prevents focus restoration to the *trigger*, but does NOT prevent the content element itself from receiving focus during close.

**2. Radix applies `aria-hidden` to the app root**

When a Radix component (DropdownMenu, Popover, etc.) opens, it sets `aria-hidden="true"` on sibling elements of its portal to hide background content from screen readers. If a custom dialog renders *inside* the app root (not via a portal), the browser spec requires defocusing any element inside an `aria-hidden` ancestor -- so the input gets forcibly blurred.

### Solution (in `frontend/src/components/ui/dialog.tsx`)

**Portal to `document.body`:** The custom Dialog uses `createPortal(…, document.body)` so it renders as a sibling of the app root, outside any `aria-hidden` tree. This is the same pattern Radix uses for its own dialogs.

**Focus guard:** After focusing the autofocus target via `queueMicrotask`, the Dialog listens for `focusout` events on its container for 500ms. If focus leaves the dialog container (e.g., a closing Radix dropdown stealing it), the guard immediately re-asserts focus on the autofocus target. The guard auto-removes after 500ms so it doesn't interfere with normal user interactions (tabbing, clicking other elements within the dialog).

**`data-autofocus` attribute:** Elements that should receive focus when the dialog opens are marked with `data-autofocus` instead of the native `autoFocus` HTML attribute. The Dialog's focus effect queries for `[data-autofocus]` first, then falls back to the first focusable element. This works reliably with React's StrictMode double-mount (unlike native `autoFocus` which only fires on initial mount).

## Modal layer: trap, background, and focus return

`useModalLayer` (`frontend/src/components/ui/modalLayer.ts`) makes an open dialog a real modal. `Dialog` uses it, and so does `ImageViewer`, which is portalled to `<body>` for the purpose.

- **Background.** While open, every other child of `<body>` gets the `inert` attribute: unfocusable, unclickable, and hidden from screen readers. That is the focus trap — Tab can't reach the page underneath. Radix popovers opened *from inside* the dialog portal to `<body>` afterwards, so they stay usable. Nested dialogs stack: each one inerts what's beneath it and removes only the attributes it set.
- **Exemptions.** Body children marked `data-modal-exempt` are left alone. The toaster is portalled out of the app root with that attribute (in `App.tsx`) so toasts stay usable over a dialog.
- **Focus return.** On close, focus goes back to the element that was focused when the dialog opened. If that was an item in a Radix menu (which unmounts with the menu), it goes to the menu's trigger instead, found through the menu's `aria-labelledby`. `GroupCard` only prevents Radix's own focus return when an item has opened a dialog, so Escape out of the menu still lands on the trigger.
- **Naming.** `DialogContent` sets `role="dialog"`, `aria-modal` and `aria-labelledby`; a `DialogTitle` or `PanelTitle` inside picks up the id through `DialogTitleIdContext` and becomes the heading. Pass `aria-label` instead when the dialog has no visible title.
- **Escape** still goes through `dialogStack` (topmost dialog only). The viewer and the activity dock check `isAnyDialogOpen()` before acting on Escape.

The 500ms focus guard described above remains, for the dropdown race at open time.

### Where this applies

Any custom `Dialog` opened from a Radix-managed component (DropdownMenu, ContextMenu, Popover) is susceptible. The fix is in the shared `Dialog` component, so all consumers benefit automatically. The `onCloseAutoFocus` prop on `DropdownMenuContent` is also applied at trigger sites as a secondary defense:

- `frontend/src/components/GroupCard.tsx` - gallery card action menu
- `frontend/src/components/EditGroupDialog.tsx` - per-group action menu

### Key files

- `frontend/src/components/ui/dialog.tsx` - portal + focus guard implementation
- `frontend/src/components/ui/modalLayer.ts` - inert background, focus return
- `frontend/src/components/ui/confirm-dialog.tsx` - uses `data-autofocus` on confirm button
- `frontend/src/components/GroupPickerShell.tsx` - uses `data-autofocus` on search input
