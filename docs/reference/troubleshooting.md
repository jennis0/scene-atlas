# Troubleshooting

## Where the Logs Are

| Running as | Log |
|------------|-----|
| Desktop app | `backend.log` and `updater.log` in the app's settings folder (`%APPDATA%\Scene Atlas`, `~/Library/Application Support/Scene Atlas` or `~/.config/Scene Atlas`), and `logs/scene-atlas.log` in *Search data* |
| Docker | `docker compose logs -f` |
| Standalone | `logs/scene-atlas.log` in `APP_DATA_DIR` |

Startup refusals start with `STARTUP ERROR:` and say what's wrong.

## Starting Up

**"Another Scene Atlas backend is already using the folder…"**: two copies of Scene Atlas are pointed at the same library. Close the other one. A leftover `.backend.lock` file on its own is harmless.

**"The image folder belongs to a different library"**, **"…doesn't contain this library's images"** or **"…whose search data folder isn't here"**: *Search data* and *Imported images* don't match. This usually means a drive isn't connected or a folder was moved. Reconnect it, or point Scene Atlas at the right folders; see [Moving the library](/guide/library#moving-the-library). The desktop app offers **Try again** and **Choose folders…**.

**"The image folder (or search data folder) can't be your images folder or contain it"**: *Imported images* and *Search data* can sit inside your own folder, but can't be it or a folder above it. Choose another folder, or on a server change `IMAGE_LIBRARY_DIR`, `APP_DATA_DIR` or `LINKED_LIBRARY_DIR`.

**Port 8000 is already in use**: in Docker, set `PORT=8001` in `.env`. Standalone, pass `--port 8001` to uvicorn. The desktop app picks a free port itself.

**The app won't open on Windows or macOS**: the installers aren't signed yet. See [First-Launch Warnings](/deploy/desktop#first-launch-warnings).

## Importing

**Imports are paused**: the Activity list says why. Common reasons are no search model yet (it's still downloading), a full disk, or an image folder that can't be reached. Imports carry on once it's fixed; **Try again now** checks straight away.

**An import is "Waiting for" a folder**: the drive or share you imported from in the desktop app isn't connected. Reconnect it, or cancel the import.

**"Upload interrupted"**: the browser stopped sending files. Choose the same files or folder again to send the rest, or **Finish without them**.

**Imports are slow**: processing is mostly the search model. A GPU helps most; on a CPU, the Small model is much faster than Medium or Large. Raising *Parallel image processing* above 4 rarely helps.

**Large uploads fail behind a reverse proxy**: the proxy must allow large request bodies, for example `client_max_body_size 2G;` in Nginx. Its rate limits must allow many requests a second, because each file is one request.

**Some images were skipped**: check the import report's **Skipped** section. Auto skips images that look like tokens or aren't maps or scenes; **Include** imports them.

## Your Own Folder

**New images in the folder don't appear**: Scene Atlas checks every 15 minutes by default. Use **Settings → Library → Check for changes**.

**"\<folder\> isn't available"**: the folder's drive or network share isn't connected. Search and thumbnails still work; full-size images come back when the folder does.

## Searching

**Searches return nothing or only keyword matches**: the search model may not be downloaded or may still be loading. The top bar shows its status. On a desktop app without internet access, the first download can't happen.

**Colour filters match too much or too little**: change **Settings → General → Colour match**.

**CORS errors in the browser console**: behind a reverse proxy, set `CORS_ORIGINS` to the address you open Scene Atlas on. See the [Configuration Reference](/deploy/configuration#network).

## Memory and Speed

**High memory use**: the Large model can use 2–4 GB of RAM. Switch to Small in **Settings → Search Model**, or lower *Parallel image processing*.

**Model download fails**: check your internet connection, then try again from **Settings → Search Model**.
