/**
 * Launching and observing the packaged desktop app (dist-electron/*-unpacked).
 *
 * Each launch gets a throwaway profile: its own Chromium user data dir (so its own
 * single-instance lock and config) and, when seeded, its own storage roots. Nothing
 * touches the developer's real Scene Atlas install or library.
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
  appData: string;
  images: string;
  backendLog: string;
}

/** A fresh profile; with seedConfig the app skips the setup window and starts the backend. */
export function makeProfile(seedConfig: boolean): Profile {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "scene-atlas-packaged-"));
  const profile: Profile = {
    root,
    userData: path.join(root, "user-data"),
    appData: path.join(root, "app-data"),
    images: path.join(root, "images"),
    backendLog: path.join(root, "user-data", "backend.log"),
  };
  fs.mkdirSync(profile.userData);
  if (seedConfig) {
    fs.writeFileSync(
      path.join(profile.userData, "scene-atlas-config.json"),
      JSON.stringify({ appDataDir: profile.appData, imageLibraryDir: profile.images }),
    );
  }
  return profile;
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
    { stdio: "ignore" },
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
