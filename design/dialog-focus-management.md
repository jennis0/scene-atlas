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

### Where this applies

Any custom `Dialog` opened from a Radix-managed component (DropdownMenu, ContextMenu, Popover) is susceptible. The fix is in the shared `Dialog` component, so all consumers benefit automatically. The `onCloseAutoFocus` prop on `DropdownMenuContent` is also applied at trigger sites as a secondary defense:

- `frontend/src/components/GroupCard.tsx` - gallery card action menu
- `frontend/src/components/EditGroupDialog.tsx` - per-group action menu

### Key files

- `frontend/src/components/ui/dialog.tsx` - portal + focus guard implementation
- `frontend/src/components/ui/confirm-dialog.tsx` - uses `data-autofocus` on confirm button
- `frontend/src/components/GroupPickerShell.tsx` - uses `data-autofocus` on search input
