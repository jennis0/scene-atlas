/**
 * Launching and observing the packaged desktop app (dist-electron/*-unpacked).
 *
 * Each launch gets a throwaway profile: its own Chromium user data dir (so its own
 * single-instance lock and config), its own storage roots and, for a first launch, its
 * own default folders (see launch()). Nothing touches the developer's real Scene Atlas
 * install or library.
 *
 * The app is driven over the Chrome DevTools Protocol (--remote-debugging-port), not
 * Playwright's _electron.launch: that needs Node's --inspect, which the packaged app's
 * fuses turn off (design/electron.md#fuses).
 */
import { chromium, type Browser, type Page } from "@playwright/test";
import { execFile, spawn, type ChildProcess } from "child_process";
import fs from "fs";
import net from "net";
import os from "os";
import path from "path";
import { promisify } from "util";

const execFileAsync = promisify(execFile);
const ROOT = path.resolve(__dirname, "..", "..");
const DIST = path.join(ROOT, "dist-electron");

/** The unpacked app's executable for this platform. */
export function appExecutable(): string {
  const candidates: Record<string, string> = {
    win32: path.join(DIST, "win-unpacked", "Scene Atlas.exe"),
    linux: path.join(DIST, "linux-unpacked", "scene-atlas"),
    darwin: path.join(DIST, "mac-arm64", "Scene Atlas.app", "Contents", "MacOS", "Scene Atlas"),
  };
  const exe = process.env.SCENE_ATLAS_EXE ?? candidates[process.platform];
  if (!exe || !fs.existsSync(exe)) {
    throw new Error(
      `Packaged app not found at ${exe}. Build it first: ` +
        "uv run python scripts/build/build_electron.py --dev",
    );
  }
  return exe;
}

export interface Profile {
  root: string;
  userData: string;
  /** The folders a seeded config names */
  appData: string;
  images: string;
  /** Where a first launch puts a new library (the app's defaults, redirected by launch()) */
  defaults: { appData: string; store: string };
  /** The fake home folder launch() points the OS's Documents lookup at (macOS, Linux) */
  home: string;
  backendLog: string;
}

/** Extra config keys for a seeded profile, e.g. libraryChosen or linkedLibraryDir. */
export type SeedConfig = Record<string, unknown>;

/**
 * A fresh profile. Unseeded, the app starts as on a first launch: a provisional library on
 * the default folders. Seeded, its config names the profile's own folders; a config with no
 * libraryChosen key counts as chosen (one written before the setup wizard chose folders),
 * so pass { libraryChosen: false } for a library whose setup is still at the library step.
 */
export function makeProfile(seedConfig: boolean | SeedConfig): Profile {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "scene-atlas-packaged-"));
  const home = path.join(root, "home");
  // electron/src/storageDirs.ts defaultStorageBase: Local AppData on Windows, else Documents.
  const defaultBase =
    process.platform === "win32"
      ? path.join(home, "AppData", "Local", "Scene Atlas")
      : path.join(home, "Documents", "Scene Atlas");
  const profile: Profile = {
    root,
    userData: path.join(root, "user-data"),
    appData: path.join(root, "app-data"),
    images: path.join(root, "images"),
    defaults: { appData: path.join(defaultBase, "data"), store: path.join(defaultBase, "images") },
    home,
    backendLog: path.join(root, "user-data", "backend.log"),
  };
  fs.mkdirSync(profile.userData);
  fs.mkdirSync(path.join(home, ".config"), { recursive: true });
  if (seedConfig) {
    fs.writeFileSync(
      configPath(profile),
      JSON.stringify({
        appDataDir: profile.appData,
        imageLibraryDir: profile.images,
        ...(seedConfig === true ? {} : seedConfig),
      }),
    );
  }
  return profile;
}

export function configPath(profile: Profile): string {
  return path.join(profile.userData, "scene-atlas-config.json");
}

export function readConfig(profile: Profile): Record<string, unknown> {
  return JSON.parse(fs.readFileSync(configPath(profile), "utf8"));
}

/**
 * Environment that moves the app's default folders into the profile, so a first launch
 * never creates or opens the developer's real library:
 * - Windows: LOCALAPPDATA, which defaultStorageBase reads itself.
 * - Linux: XDG_CONFIG_HOME with a user-dirs.dirs naming the Documents folder, which
 *   Chromium's Documents lookup (app.getPath('documents')) reads.
 * - macOS: CFFIXED_USER_HOME, which Foundation's home folder lookup honours.
 */
function defaultFolderEnv(profile: Profile): NodeJS.ProcessEnv {
  if (process.platform === "win32") {
    return { LOCALAPPDATA: path.join(profile.home, "AppData", "Local") };
  }
  if (process.platform === "darwin") return { CFFIXED_USER_HOME: profile.home };
  const configHome = path.join(profile.home, ".config");
  const documents = path.join(profile.home, "Documents");
  fs.writeFileSync(
    path.join(configHome, "user-dirs.dirs"),
    `XDG_DOCUMENTS_DIR="${documents}"\n`,
  );
  return { XDG_CONFIG_HOME: configHome };
}

export interface RunningApp {
  child: ChildProcess;
  cdpPort: number;
  browser: Browser;
}

async function freePort(): Promise<number> {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      server.close(() =>
        typeof address === "object" && address ? resolve(address.port) : reject(),
      );
    });
  });
}

/** Start the app on a profile; resolves once its DevTools endpoint accepts a connection. */
export async function launch(profile: Profile, extraArgs: string[] = []): Promise<RunningApp> {
  const cdpPort = await freePort();
  const child = spawn(
    appExecutable(),
    [`--user-data-dir=${profile.userData}`, `--remote-debugging-port=${cdpPort}`, ...extraArgs],
    { stdio: "ignore", env: { ...process.env, ...defaultFolderEnv(profile) } },
  );
  let exited = false;
  child.once("exit", () => (exited = true));
  // A second instance quits before it serves DevTools: stop waiting when it does.
  return { child, cdpPort, browser: await connect(cdpPort, 60_000, () => exited) };
}

/** Connect over CDP, retrying while the app starts (or relaunches) on that port. */
export async function connect(
  cdpPort: number,
  timeoutMs = 60_000,
  gone: () => boolean = () => false,
): Promise<Browser> {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    try {
      return await chromium.connectOverCDP(`http://127.0.0.1:${cdpPort}`);
    } catch (err) {
      if (gone() || Date.now() > deadline) throw err;
      await sleep(250);
    }
  }
}

/** The first open page whose URL matches. */
export async function waitForPage(
  browser: Browser,
  matches: (url: string) => boolean,
  timeoutMs = 180_000,
): Promise<Page> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    for (const context of browser.contexts()) {
      const page = context.pages().find((p) => matches(p.url()));
      if (page) return page;
    }
    await sleep(250);
  }
  const urls = browser.contexts().flatMap((c) => c.pages().map((p) => p.url()));
  throw new Error(`No page matched within ${timeoutMs} ms; open pages: ${urls.join(", ")}`);
}

/** The window once it has left the loading page for the UI the backend serves. */
export function waitForBackendUi(browser: Browser): Promise<Page> {
  return waitForPage(browser, (url) => /^http:\/\/127\.0\.0\.1:\d+\//.test(url));
}

export interface LibraryDirs {
  appData: string;
  store: string;
  linked: string | null;
}

/** electronAPI.applyLibrary from the UI. Awaited, it settles only when nothing restarts. */
export function applyLibrary(
  page: Page,
  dirs: LibraryDirs,
): Promise<{ error: string | null; restarted: boolean }> {
  return page.evaluate((d) => (window as any).electronAPI.applyLibrary(d), dirs);
}

/** Wait until the window has reloaded the UI with libraryChosen set (after a restart). */
export async function waitForChosenLibraryUi(page: Page, timeoutMs = 180_000): Promise<void> {
  await waitUntil(
    "the UI to reload on the new backend",
    async () =>
      /^http:\/\/127\.0\.0\.1:\d+\//.test(page.url()) &&
      (await page
        .evaluate(() => (window as any).electronAPI.libraryChosen === true)
        .catch(() => false)),
    timeoutMs,
  );
}

interface ProcessInfo {
  pid: number;
  ppid: number;
  command: string;
}

/** Every process on the machine, with its command line. */
async function listProcesses(): Promise<ProcessInfo[]> {
  if (process.platform === "win32") {
    const { stdout } = await execFileAsync(
      "powershell.exe",
      [
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        "Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId,CommandLine | ConvertTo-Json -Compress",
      ],
      { maxBuffer: 64 * 1024 * 1024 },
    );
    const rows = JSON.parse(stdout) as {
      ProcessId: number;
      ParentProcessId: number;
      CommandLine: string | null;
    }[];
    return rows.map((r) => ({ pid: r.ProcessId, ppid: r.ParentProcessId, command: r.CommandLine ?? "" }));
  }
  const { stdout } = await execFileAsync("ps", ["-eo", "pid=,ppid=,args="], {
    maxBuffer: 64 * 1024 * 1024,
  });
  return stdout
    .split("\n")
    .map((line) => line.trim().match(/^(\d+)\s+(\d+)\s+(.*)$/))
    .filter((m): m is RegExpMatchArray => m !== null)
    .map((m) => ({ pid: Number(m[1]), ppid: Number(m[2]), command: m[3] }));
}

/** Processes whose command line mentions the given path (profile dirs are unique per test). */
export async function processesMentioning(fragment: string): Promise<ProcessInfo[]> {
  return (await listProcesses()).filter((p) => p.command.includes(fragment));
}

/** The backend sidecar(s) serving a given app data root. */
export async function sidecars(appDataDir: string): Promise<ProcessInfo[]> {
  return (await processesMentioning(appDataDir)).filter((p) =>
    /scene-atlas-backend/i.test(p.command),
  );
}

/** Electron main process(es) for a profile: Chromium helpers carry a --type= switch. */
export async function mainProcesses(profile: Profile): Promise<ProcessInfo[]> {
  return (await processesMentioning(profile.userData)).filter(
    (p) => !p.command.includes("--type=") && !/scene-atlas-backend/i.test(p.command),
  );
}

export function isAlive(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

/** Poll until the condition holds; throws with the description on timeout. */
export async function waitUntil(
  description: string,
  condition: () => boolean | Promise<boolean>,
  timeoutMs = 30_000,
): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (await condition()) return;
    await sleep(250);
  }
  throw new Error(`Timed out after ${timeoutMs} ms waiting for: ${description}`);
}

/** Kill anything still running from the profile, then delete it. */
export async function cleanUp(profile: Profile): Promise<void> {
  for (const p of await processesMentioning(profile.root)) {
    try {
      process.kill(p.pid, "SIGKILL");
    } catch {
      // Already gone.
    }
  }
  // Windows keeps files locked briefly after the processes exit.
  for (let attempt = 0; attempt < 20; attempt++) {
    try {
      fs.rmSync(profile.root, { recursive: true, force: true });
      return;
    } catch {
      await sleep(500);
    }
  }
}

export function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
