# First-run experience

What a new user sees, in both deployment modes, and why. Decisions recorded 2026-10-18.

## Flow

| | Desktop app | Server |
|---|---|---|
| Storage window (`electron/setup.html`, before the backend exists) | App data folder and image library folder. Follows the system light/dark setting | — |
| Loading page (`electron/loading.html`) | "Starting up…", or the startup error. Follows the system setting | — |
| Setup wizard (React, `components/setup/SetupWizard.tsx`) | Appearance (and how the app updates) → Stored format → Tag packs → Search model | same, without updates |
| Gallery | Empty-library screen; the model downloads in the background | same |

The wizard runs once per library, until `POST /models/setup-complete` records `setup_completed_at`. The server isn't a shared multi-user service yet, so the appearance step isn't repeated for each new browser. When it becomes one, appearance needs its own per-device "first visit" flag, because display choices are stored per device.

### Why each step is where it is

- **Storage folders stay in the Electron window.** The backend can't start without them, so they're chosen before React exists. On a server they're env vars (`APP_DATA_DIR`, `IMAGE_LIBRARY_DIR`) and the UI never shows server paths.
- **Appearance comes first**, so the rest of setup is already in the user's theme and text size. Every change applies at once and is saved per device (`ThemeContext`).
- **The desktop app's update choice is on the first step**, so it's made before the app first contacts GitHub ([electron.md](electron.md#updates)). It starts on Ask first; leaving it there records Ask first when setup finishes. A server's checks are its admin's (`CHECK_FOR_UPDATES`), so the server wizard doesn't show it.
- **Stored format is in the wizard, not the Electron window.** It's a library setting (`stored_format`), so both modes set it the same way via `PATCH /settings/`. On a server, `CONVERT_TO_WEBP=1` only changes the default the wizard starts with. This removed the Electron `pendingStoredFormat` handoff.
- **Every tag pack is optional, Common included.** Common is installed when the library is created; the tag-pack step then installs exactly what the user picks (`PUT /tags/packs`, refused once setup is finished; see [tag-packs.md](tag-packs.md)).
- **The server keeps the model and tag-pack steps.** They're choices about library content, not deployment config. `EMBEDDING_MODEL` still overrides the model; when a model is already set up, the model step is skipped.
- **The search model is last, and Finish starts its download.** Earlier, the download ran during the tag-pack step and the wizard could end on "Waiting for model setup to finish…" for minutes. Now the wizard ends right away and the gallery's empty-library screen waits for the model. Putting it last also keeps Back simple: no download is running while earlier steps can still change.

### Copy

Keep setup text short and plain. Say what each step is for and, where there is one, the trade-off ("Larger models give better results but make importing slower"). Leave out reassurance and mechanics the user doesn't act on ("Changes apply straight away", "saved on this device", what happens to files behind the scenes). Keep warnings that prevent data loss, such as not choosing an existing maps folder as the image library. Use "Couldn't" in errors, and sentence case.

### Gate (`App.tsx`)

`GET /models/setup-status` returns `setup_completed` and `model_activating` alongside `needs_model`:

- Setup not completed → the full wizard (the model step only if `needs_model`).
- Setup completed, no model, and no activation running → the wizard with only the model step (e.g. the model folder was deleted).
- Otherwise → the gallery. While a model downloads, the gallery shows it as loading.

## Theme

`ThemeContext` keeps a preference, `system` | `light` | `dark` (`scene-atlas-theme`), defaulting to `system`, and resolves it to `light` | `dark` for consumers. With `system`, a change in the OS setting applies live (`lib/theme.ts`). The header's sun/moon button sets an explicit light or dark. Libraries set up before this change that never chose a theme switch from dark to following the system.

### Desktop: display choices and window colours

Display choices (theme, palette, text size, zoom, contrast, compact header) are kept through `lib/prefsStorage.ts`, which uses localStorage. In the desktop app the UI's origin is the backend's, port included, so if port 47816 is taken at launch that localStorage is a different, empty one. So the app config keeps a copy too:

- The preload reads `displayPrefs` from the config with one synchronous IPC call (`prefs:get-sync`) before the page runs, and exposes it as `electronAPI.displayPrefs`. At startup `syncPrefsWithDesktop()` (in `main.tsx`, before the first paint) copies those values into localStorage, which may be another port's or stale. Values only localStorage has, saved before the config kept them, are copied into the config, so an update resets nobody's choices.
- Every change is written to both (`electronAPI.setDisplayPref` → `prefs:set`). The main process accepts only `scene-atlas-*` keys with short lower-case values, at most 32 (`electron/src/displayPrefs.ts`).
- The main process sets `nativeTheme.themeSource` from the saved theme (System, Light or Dark) at startup and on every change. Chromium's `prefers-color-scheme` therefore follows the user's choice in every window, so the storage window, loading page, native dialogs and scrollbars match the app. With System, they follow the OS.
- Whenever the theme, palette or effective contrast changes, `ThemeProvider` reports the body's computed background and text colours (`reportWindowColors`, `window:set-colors`). The main process sets the window background and, on Windows, the title-bar overlay (`setTitleBarOverlay`), and saves them as `windowColors`, so the next launch opens in them. Before the UI has reported any colours, windows use the navy palette for the current light/dark.

Other per-device conveniences (tile size, sort, view mode, grid overlay, custom filter colours) still use localStorage directly and don't survive a port change. They can move to `prefsStorage` if that matters.

## Known gaps

- Windows High Contrast (forced colours) is only handled in the setup wizard and the controls it shares with Settings.
- The title-bar overlay colour change is covered by an Electron run under Xvfb, which can't show the overlay; check it by eye on Windows and Linux when changing it.
