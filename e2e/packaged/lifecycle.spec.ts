/**
 * The packaged desktop app: windows, the backend sidecar's lifecycle, first launch, and
 * the single-instance and library-change paths (design/electron.md#sidecar-lifecycle,
 * design/library-setup.md).
 *
 * Run after a build: npm run test:packaged (design/testing.md#packaged-app-tests).
 */
import { expect, test } from "@playwright/test";
import fs from "fs";
import path from "path";
import {
  applyLibrary,
  applyLibraryAndRestart,
  cleanUp,
  isAlive,
  launch,
  mainProcesses,
  makeProfile,
  readConfig,
  sidecars,
  waitForBackendUi,
  waitForLoadingPage,
  waitUntil,
  writeConfig,
  type Profile,
} from "./app";

let profile: Profile;

test.afterEach(async () => {
  if (profile) await cleanUp(profile);
});

function backendAppLog(appDataDir: string): string {
  const log = path.join(appDataDir, "logs", "scene-atlas.log");
  return fs.existsSync(log) ? fs.readFileSync(log, "utf8") : "";
}

test("first launch opens the wizard on the default folders, in the system locale", async () => {
  profile = makeProfile(false);
  const app = await launch(profile, ["--lang=en-GB"]);
  const page = await waitForBackendUi(app.browser);
  const { defaults } = profile;

  // A provisional library on the defaults, which the backend runs on straight away.
  expect(readConfig(profile)).toMatchObject({
    appDataDir: defaults.appData,
    imageLibraryDir: defaults.store,
    provisional: true,
    libraryChosen: false,
  });
  const [sidecar, ...extra] = await sidecars(defaults.appData);
  expect(extra).toHaveLength(0);
  expect(sidecar.command).not.toContain("--linked-library-dir");
  await expect(page.getByRole("heading", { name: "Welcome to Scene Atlas" })).toBeVisible({
    timeout: 60_000,
  });
  const api = await page.evaluate(async () => {
    const electronAPI = (window as any).electronAPI;
    return { libraryChosen: electronAPI.libraryChosen, dirs: await electronAPI.getStorageDirs() };
  });
  expect(api).toEqual({
    libraryChosen: false,
    dirs: { appData: defaults.appData, store: defaults.store, linked: null, defaults },
  });
  // en-GB ships in electronLanguages; without its .pak Chromium falls back to en-US.
  expect(await page.evaluate(() => navigator.language)).toBe("en-GB");

  // Keeping the defaults: recorded, with no restart.
  const result = await applyLibrary(page, { appData: defaults.appData, store: defaults.store, linked: null });
  expect(result).toEqual({ error: null, restarted: false });
  expect(isAlive(sidecar.pid)).toBe(true);
  expect(readConfig(profile)).toMatchObject({ provisional: false, libraryChosen: true });
  await page.reload();
  expect(await page.evaluate(() => (window as any).electronAPI.libraryChosen)).toBe(true);
});

test("an unusable storage folder is reported on the loading page, in the app's fonts", async () => {
  profile = makeProfile(false);
  // A folder can't be created inside a file, on any OS.
  const blocker = path.join(profile.root, "not-a-folder");
  fs.writeFileSync(blocker, "");
  writeConfig(profile, { appDataDir: path.join(blocker, "data"), imageLibraryDir: profile.images });
  const app = await launch(profile);
  const loading = await waitForLoadingPage(app.browser);

  await expect(loading.locator("body")).toContainText("can't be used", { timeout: 30_000 });
  const loaded = await loading.evaluate(async () => {
    await document.fonts.ready;
    return [...document.fonts].filter((f) => f.status === "loaded").map((f) => f.family);
  });
  expect(loaded.map((f) => f.replace(/['"]/g, ""))).toEqual(
    expect.arrayContaining(["Figtree", "Cinzel"]),
  );
  expect(await sidecars(profile.root)).toHaveLength(0);
});

test("folders the backend refuses can be chosen again from the loading page", async () => {
  // The image folder belongs to another library, whose search data isn't here.
  profile = makeProfile(true);
  fs.mkdirSync(profile.images, { recursive: true });
  const marker = path.join(profile.images, "scene-atlas-library.json");
  fs.writeFileSync(
    marker,
    JSON.stringify({ format: 1, library_id: "4f1c0000-0000-4000-8000-000000000000", role: "store", hints: {} }),
  );
  const app = await launch(profile);
  const loading = await waitForLoadingPage(app.browser);

  await expect(loading.getByRole("button", { name: "Try again" })).toBeVisible({ timeout: 60_000 });
  await loading.getByRole("button", { name: "Choose folders…" }).click();

  // Back on the default folders, in the same window, with the library step to show again.
  const page = await waitForBackendUi(app.browser);
  expect(await page.evaluate(() => (window as any).electronAPI.libraryChosen)).toBe(false);
  expect(readConfig(profile)).toMatchObject({
    appDataDir: profile.defaults.appData,
    imageLibraryDir: profile.defaults.store,
    provisional: true,
    libraryChosen: false,
  });
  expect(await mainProcesses(profile)).toHaveLength(1);
  // The refused folders are left as they were.
  expect(fs.existsSync(marker)).toBe(true);
  expect(fs.existsSync(path.join(profile.appData, "battlemap.db"))).toBe(false);
});

test("serves the UI from the backend; closing the window stops the backend", async () => {
  profile = makeProfile(true);
  const app = await launch(profile);
  const page = await waitForBackendUi(app.browser);
  await expect(page.locator("h1").first()).toBeVisible({ timeout: 60_000 });
  expect((await page.request.get(new URL("/health", page.url()).href)).ok()).toBe(true);

  const [sidecar, ...extra] = await sidecars(profile.appData);
  expect(extra).toHaveLength(0);
  expect(sidecar.ppid).toBe(app.child.pid);

  // The app waits for the backend before exiting, so the shutdown finishes: on Windows
  // the backend dies with the app (libuv's kill-on-close job object).
  await page.evaluate(() => window.close());
  await waitUntil("backend to exit", () => !isAlive(sidecar.pid), 30_000);
  await waitUntil("app to quit", () => !isAlive(app.child.pid!));
  expect(backendAppLog(profile.appData)).toContain("Shutdown complete");
});

test("the backend doesn't outlive a killed app", async () => {
  profile = makeProfile(true);
  const app = await launch(profile);
  await waitForBackendUi(app.browser);
  const [sidecar] = await sidecars(profile.appData);

  // TerminateProcess on Windows, SIGKILL elsewhere: no will-quit, no stopSidecar().
  app.child.kill("SIGKILL");
  await waitUntil("backend to exit", () => !isAlive(sidecar.pid), 30_000);
  if (process.platform !== "win32") {
    // The backend's watchdog notices and shuts down gracefully. On Windows the job
    // object terminates it with the app instead.
    const log = backendAppLog(profile.appData);
    expect(log).toContain("Desktop app is gone");
    expect(log).toContain("Shutdown complete");
  }

  // The storage locks were released: a new launch on the same folders starts.
  const again = await launch(profile);
  await waitForBackendUi(again.browser);
});

test("a second launch exits and leaves the first running", async () => {
  profile = makeProfile(true);
  const first = await launch(profile);
  await waitForBackendUi(first.browser);

  const second = await launch(profile).catch(() => null);
  // The second instance hands over to the first and quits before serving DevTools,
  // or shortly after; either way it must not start another backend.
  if (second) await waitUntil("second instance to quit", () => !isAlive(second.child.pid!));
  expect(isAlive(first.child.pid!)).toBe(true);
  expect(await sidecars(profile.appData)).toHaveLength(1);
});

test("choosing other folders in setup restarts the backend in the window and deletes the provisional ones", async () => {
  profile = makeProfile(false);
  const app = await launch(profile);
  const page = await waitForBackendUi(app.browser);
  const [oldSidecar] = await sidecars(profile.defaults.appData);
  expect(fs.existsSync(profile.defaults.store)).toBe(true);

  // The user's maps folder, linked, with the store inside it (the wizard's default).
  const maps = path.join(profile.root, "Battle Maps");
  fs.mkdirSync(maps);
  fs.writeFileSync(path.join(maps, "notes.txt"), "mine");
  const newAppData = path.join(profile.root, "search-data");
  const store = path.join(maps, "Scene Atlas");

  // Refused before anything happens: the store can't be the linked folder.
  expect(await applyLibrary(page, { appData: newAppData, store: maps, linked: maps })).toMatchObject({
    error: expect.stringContaining("Imported maps"),
    restarted: false,
  });
  expect(isAlive(oldSidecar.pid)).toBe(true);

  await applyLibraryAndRestart(page, { appData: newAppData, store, linked: maps }, oldSidecar.pid);

  // Same app process and window; a new backend on the new folders, with the linked one.
  expect(isAlive(app.child.pid!)).toBe(true);
  expect(await mainProcesses(profile)).toHaveLength(1);
  const [newSidecar, ...extra] = await sidecars(newAppData);
  expect(extra).toHaveLength(0);
  expect(newSidecar.command).toContain("--linked-library-dir");
  expect(fs.existsSync(path.join(newAppData, "battlemap.db"))).toBe(true);
  expect(readConfig(profile)).toMatchObject({
    appDataDir: newAppData,
    imageLibraryDir: store,
    linkedLibraryDir: maps,
    provisional: false,
    libraryChosen: true,
  });

  // The provisional library is gone; the user's own files are as they were.
  expect(fs.existsSync(profile.defaults.appData)).toBe(false);
  expect(fs.existsSync(profile.defaults.store)).toBe(false);
  expect(fs.readFileSync(path.join(maps, "notes.txt"), "utf8")).toBe("mine");
});

test("changing folders later restarts the backend in the window and keeps the old ones", async () => {
  profile = makeProfile(true);
  const app = await launch(profile);
  const page = await waitForBackendUi(app.browser);
  const [oldSidecar] = await sidecars(profile.appData);

  const newAppData = path.join(profile.root, "moved-app-data");
  const newImages = path.join(profile.root, "moved-images");
  await applyLibraryAndRestart(page, { appData: newAppData, store: newImages, linked: null }, oldSidecar.pid);
  expect(isAlive(app.child.pid!)).toBe(true);
  const [newSidecar] = await sidecars(newAppData);
  expect(newSidecar).toBeDefined();
  expect(await mainProcesses(profile)).toHaveLength(1);
  expect(fs.existsSync(path.join(newAppData, "battlemap.db"))).toBe(true);
  // Moving the files is the user's job (Settings says so): the old folders stay.
  expect(fs.existsSync(path.join(profile.appData, "battlemap.db"))).toBe(true);
  expect(readConfig(profile)).toMatchObject({ appDataDir: newAppData, imageLibraryDir: newImages });
});
