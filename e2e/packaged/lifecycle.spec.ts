/**
 * The packaged desktop app: windows, the backend sidecar's lifecycle, and the
 * single-instance and storage-change paths (design/electron.md#sidecar-lifecycle).
 *
 * Run after a build: npm run test:packaged (design/testing.md#packaged-app-tests).
 */
import { expect, test } from "@playwright/test";
import fs from "fs";
import path from "path";
import {
  cleanUp,
  connect,
  isAlive,
  launch,
  mainProcesses,
  makeProfile,
  sidecars,
  waitForBackendUi,
  waitForPage,
  waitUntil,
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

test("first launch shows the setup window, offline fonts and the system locale", async () => {
  profile = makeProfile(false);
  const app = await launch(profile, ["--lang=en-GB"]);
  const setup = await waitForPage(app.browser, (url) => url.endsWith("/setup.html"));

  // Bundled fonts load from file:// (no network, no extra file:// privileges).
  const loaded = await setup.evaluate(async () => {
    await document.fonts.ready;
    return [...document.fonts].filter((f) => f.status === "loaded").map((f) => f.family);
  });
  expect(loaded.map((f) => f.replace(/['"]/g, ""))).toEqual(
    expect.arrayContaining(["Figtree", "Cinzel"]),
  );
  // en-GB ships in electronLanguages; without its .pak Chromium falls back to en-US.
  expect(await setup.evaluate(() => navigator.language)).toBe("en-GB");

  // No backend until setup completes; closing setup quits the app.
  expect(await sidecars(profile.appData)).toHaveLength(0);
  await setup.evaluate(() => window.close());
  await waitUntil("app to quit", () => !isAlive(app.child.pid!));
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

test("changing storage folders relaunches onto the new folders", async () => {
  profile = makeProfile(true);
  const app = await launch(profile);
  const page = await waitForBackendUi(app.browser);
  const [oldSidecar] = await sidecars(profile.appData);

  const newAppData = path.join(profile.root, "moved-app-data");
  const newImages = path.join(profile.root, "moved-images");
  // Doesn't resolve on success: the app exits and relaunches (same arguments).
  void page
    .evaluate(
      ([a, i]) => (window as any).electronAPI.changeStorageDirs(a, i),
      [newAppData, newImages],
    )
    .catch(() => {});

  await waitUntil("old app to exit", () => !isAlive(app.child.pid!), 30_000);
  await waitUntil("old backend to exit", () => !isAlive(oldSidecar.pid), 30_000);

  const relaunched = await connect(app.cdpPort);
  await waitForBackendUi(relaunched);
  const [newSidecar] = await sidecars(newAppData);
  expect(newSidecar).toBeDefined();
  expect(await mainProcesses(profile)).toHaveLength(1);
  expect(fs.existsSync(path.join(newAppData, "battlemap.db"))).toBe(true);

  const config = JSON.parse(
    fs.readFileSync(path.join(profile.userData, "scene-atlas-config.json"), "utf8"),
  );
  expect(config).toMatchObject({ appDataDir: newAppData, imageLibraryDir: newImages });
});
