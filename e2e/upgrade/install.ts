/**
 * Installing a build for real, and serving a newer build as its update feed
 * (design/testing.md#upgrade-test). On Windows this installs into the current user's
 * registry and Start menu, so the spec only runs where that is safe: CI, or with
 * SCENE_ATLAS_UPGRADE_TEST=1 on a machine without a Scene Atlas install you care about.
 * On Linux the "install" is an AppImage in a folder.
 */
import { execFile } from "child_process";
import fs from "fs";
import http from "http";
import path from "path";
import { promisify } from "util";

const execFileAsync = promisify(execFile);

const INSTALLED_EXE = "Scene Atlas.exe";
const UNINSTALLER = "Uninstall Scene Atlas.exe";
/** The updater's download folder (and so its installer's path) is named after this. */
export const UPDATER_MARKER = "scene-atlas-updater";

/** Install *installer* into *dir* and return the app's executable: a per-user silent NSIS
 * install on Windows (/D must be last and unquoted), a copy of the AppImage on Linux. */
export async function install(installer: string, dir: string): Promise<string> {
  fs.mkdirSync(dir, { recursive: true });
  if (process.platform === "linux") {
    const appImage = path.join(dir, path.basename(installer));
    fs.copyFileSync(installer, appImage);
    fs.chmodSync(appImage, 0o755);
    return appImage;
  }
  await execFileAsync(installer, ["/S", "/currentuser", `/D=${dir}`], { timeout: 10 * 60_000 });
  const exe = path.join(dir, INSTALLED_EXE);
  if (!fs.existsSync(exe)) throw new Error(`The installer finished but ${exe} is missing`);
  return exe;
}

export async function uninstall(dir: string): Promise<void> {
  const uninstaller = path.join(dir, UNINSTALLER);
  if (process.platform !== "win32" || !fs.existsSync(uninstaller)) return;
  await execFileAsync(uninstaller, ["/S", "/currentuser"], { timeout: 5 * 60_000 }).catch(() => {});
}

/** The installed executable's product version, as electron-builder stamps it (Windows). */
async function productVersion(exe: string): Promise<string> {
  const { stdout } = await execFileAsync("powershell.exe", [
    "-NoProfile",
    "-NonInteractive",
    "-Command",
    `(Get-Item -LiteralPath '${exe.replace(/'/g, "''")}').VersionInfo.ProductVersion`,
  ]);
  return stdout.trim();
}

/**
 * The executable once the update to *version* is installed, or null while it isn't. The
 * NSIS installer replaces the files in place; the AppImage updater moves the new AppImage
 * in under its own versioned name and deletes the old one.
 */
export async function updatedExecutable(
  dir: string,
  exe: string,
  version: string,
): Promise<string | null> {
  if (process.platform === "linux") {
    const updated = path.join(dir, `Scene-Atlas-${version}-x86_64.AppImage`);
    return fs.existsSync(updated) && !fs.existsSync(exe) ? updated : null;
  }
  return (await productVersion(exe)) === version ? exe : null;
}

/**
 * Environment that keeps the updater's download cache inside *root*, and with it the
 * copy of the app the installer starts again afterwards (on the default profile).
 */
export function isolatedEnv(root: string): Record<string, string> {
  if (process.platform === "win32") return { LOCALAPPDATA: path.join(root, "local-app-data") };
  return {
    XDG_CACHE_HOME: path.join(root, "xdg-cache"),
    XDG_CONFIG_HOME: path.join(root, "xdg-config"),
  };
}

export interface Feed {
  url: string;
  /** Paths requested, so the test can show the app fetched from the feed */
  requests: string[];
  close(): Promise<void>;
}

interface ByteRange {
  start: number;
  end: number;
}

/** The ranges of a `Range: bytes=…` header, or null to send the whole file. */
export function parseRanges(header: string | undefined, size: number): ByteRange[] | null {
  const match = header?.match(/^bytes=(.+)$/);
  if (!match) return null;
  const ranges: ByteRange[] = [];
  for (const part of match[1].split(",")) {
    const [from, to] = part.trim().split("-");
    if (from === "") {
      const suffix = Number(to);
      if (!Number.isInteger(suffix) || suffix <= 0) return null;
      ranges.push({ start: Math.max(0, size - suffix), end: size - 1 });
      continue;
    }
    const start = Number(from);
    const end = to === "" ? size - 1 : Math.min(Number(to), size - 1);
    if (!Number.isInteger(start) || !Number.isInteger(end) || start > end || start >= size) {
      return null;
    }
    ranges.push({ start, end });
  }
  return ranges.length ? ranges : null;
}

const CRLF = "\r\n";

async function sendRanges(
  res: http.ServerResponse,
  file: string,
  size: number,
  ranges: ByteRange[],
): Promise<void> {
  if (ranges.length === 1) {
    const [{ start, end }] = ranges;
    res.writeHead(206, {
      "Content-Range": `bytes ${start}-${end}/${size}`,
      "Content-Length": end - start + 1,
    });
    fs.createReadStream(file, { start, end }).pipe(res);
    return;
  }
  // Differential downloads ask for many ranges at once: multipart/byteranges.
  const boundary = "scene-atlas-feed";
  res.writeHead(206, { "Content-Type": `multipart/byteranges; boundary=${boundary}` });
  const handle = await fs.promises.open(file, "r");
  try {
    for (const { start, end } of ranges) {
      res.write(
        `--${boundary}${CRLF}Content-Type: application/octet-stream${CRLF}` +
          `Content-Range: bytes ${start}-${end}/${size}${CRLF}${CRLF}`,
      );
      const chunk = Buffer.alloc(end - start + 1);
      await handle.read(chunk, 0, chunk.length, start);
      res.write(chunk);
      res.write(CRLF);
    }
    res.end(`--${boundary}--${CRLF}`);
  } finally {
    await handle.close();
  }
}

/**
 * Serve *dir*'s files (latest.yml, the installer and the blockmaps) on 127.0.0.1, with
 * Range support so the app can download the update differentially, as it would from GitHub.
 */
export function serveFeed(dir: string): Promise<Feed> {
  const root = path.resolve(dir);
  const requests: string[] = [];
  const server = http.createServer((req, res) => {
    const name = decodeURIComponent(new URL(req.url ?? "/", "http://127.0.0.1").pathname).slice(1);
    requests.push(req.headers.range ? `${name} (ranges)` : name);
    const file = path.resolve(root, name);
    if (path.dirname(file) !== root || !fs.existsSync(file) || !fs.statSync(file).isFile()) {
      res.writeHead(404).end();
      return;
    }
    const size = fs.statSync(file).size;
    const ranges = req.method === "GET" ? parseRanges(req.headers.range, size) : null;
    if (ranges) {
      sendRanges(res, file, size, ranges).catch(() => res.destroy());
      return;
    }
    res.writeHead(200, { "Content-Length": size, "Accept-Ranges": "bytes" });
    if (req.method === "HEAD") res.end();
    else fs.createReadStream(file).pipe(res);
  });
  return new Promise((resolve, reject) => {
    server.on("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      if (!address || typeof address === "string") {
        reject(new Error("The feed server has no port"));
        return;
      }
      resolve({
        url: `http://127.0.0.1:${address.port}/`,
        requests,
        close: () => new Promise((done) => server.close(() => done())),
      });
    });
  });
}
