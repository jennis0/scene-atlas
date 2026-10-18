# First-run experience

What a new user sees, in both deployment modes, and why. Decisions recorded 2026-10-18.

## Flow

| | Desktop app | Server |
|---|---|---|
| Storage window (`electron/setup.html`, before the backend exists) | App data folder and image library folder. Follows the system light/dark setting | — |
| Loading page (`electron/loading.html`) | "Starting up…", or the startup error. Follows the system setting | — |
| Setup wizard (React, `components/setup/SetupWizard.tsx`) | Appearance → Stored format → Tag packs → Search model | same |
| Gallery | Empty-library screen; the model downloads in the background | same |

The wizard runs once per library, until `POST /models/setup-complete` records `setup_completed_at`. The server isn't a shared multi-user service yet, so the appearance step isn't repeated for each new browser. When it becomes one, appearance needs its own per-device "first visit" flag, because display choices are stored per device.

### Why each step is where it is

- **Storage folders stay in the Electron window.** The backend can't start without them, so they're chosen before React exists. On a server they're env vars (`APP_DATA_DIR`, `IMAGE_LIBRARY_DIR`) and the UI never shows server paths.
- **Appearance comes first**, so the rest of setup is already in the user's theme and text size. Every change applies at once and is saved per device (`ThemeContext`).
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

The Electron storage window and loading page can't read the app's saved choice (different origin), so they follow the system. Window background colours come from `nativeTheme.shouldUseDarkColors`.

## Known gaps

- Display choices live in the UI origin's localStorage. In the desktop app the origin includes the port, so if port 47816 is taken at launch, choices made earlier aren't found. Fix by mirroring them into the Electron config, or by serving the UI from a fixed origin.
- The Windows/Linux title-bar overlay colours are fixed to the dark navy palette.
