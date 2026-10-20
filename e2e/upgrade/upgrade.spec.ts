/**
 * The upgrade test (design/testing.md#upgrade-test): install an older build for real, give
 * it a library, update it from a local feed serving the new build, and check the library
 * and its search results came through.
 *
 * Windows (NSIS) and Linux (AppImage), the two installs that update themselves; the Release
 * workflow runs it on Windows, from a 0.0.0 build and from the last published release. It
 * provides:
 *   UPGRADE_OLD_INSTALLER  the older build's NSIS installer, or its AppImage
 *   UPGRADE_FEED_DIR       the new build's latest.yml (latest-linux.yml), installer and
 *                          blockmap, plus the old build's blockmap on Windows so the
 *                          download can be differential (an AppImage carries its own)
 *   UPGRADE_FROM_GITHUB    "1" instead of UPGRADE_FEED_DIR: update from the real GitHub
 *                          releases, to check a published release end to end
 *   UPGRADE_NEW_VERSION    the version the update must arrive at
 *   UPGRADE_MODEL_CACHE    optional: a folder that keeps the search model between runs
 *   ACCEPT_SEARCH_CHANGES  "true" to accept changed search results (never library problems)
 *   SEARCH_CHANGE_REASON   why, for the report
 *   E2E_IMAGE_KEY          to decrypt the test images (or E2E_IMAGE_DIR)
 */
import { expect, test } from "@playwright/test";
import fs from "fs";
import path from "path";
import { ensureTestImages } from "../helpers/decrypt-fixtures";
import {
  cleanUp,
  isAlive,
  launch,
  makeProfile,
  processesMentioning,
  sidecars,
  waitForBackendUi,
  waitUntil,
  type Profile,
} from "../packaged/app";
import {
  compareSnapshots,
  failsRelease,
  planQueries,
  renderReport,
  type QueryConfig,
} from "./checks";
import {
  copyInstallerCache,
  install,
  isolatedEnv,
  serveFeed,
  uninstall,
  updatedExecutable,
  UPDATER_MARKER,
  type Feed,
} from "./install";
import { activateSearchModel, buildLibrary, missingEdits, readIntegrity, takeSnapshot } from "./library";

const ROOT = path.resolve(__dirname, "..", "..");
const REPORT_DIR = process.env.UPGRADE_REPORT_DIR ?? path.join(ROOT, "e2e", "upgrade-report");
const QUERIES: QueryConfig = JSON.parse(fs.readFileSync(path.join(__dirname, "queries.json"), "utf8"));
const MODEL = "small";
const allowed = process.env.CI === "true" || process.env.SCENE_ATLAS_UPGRADE_TEST === "1";

function required(name: string): string {
  const value = process.env[name];
  if (!value) throw new Error(`${name} is not set (see the comment at the top of upgrade.spec.ts)`);
  return value;
}

type Page = Awaited<ReturnType<typeof waitForBackendUi>>;

function updateState(
  page: Page,
): Promise<{ status: string; mode: string; currentVersion: string; error?: string }> {
  return page.evaluate(() => (window as any).electronAPI.getUpdateState());
}

let profile: Profile | undefined;
let installDir: string | undefined;
let feed: Feed | undefined;

test.afterEach(async () => {
  if (profile) {
    fs.mkdirSync(REPORT_DIR, { recursive: true });
    for (const log of ["updater.log", "backend.log"]) {
      const file = path.join(profile.userData, log);
      if (fs.existsSync(file)) fs.copyFileSync(file, path.join(REPORT_DIR, log));
    }
  }
  await feed?.close();
  if (installDir) await uninstall(installDir);
  if (profile) await cleanUp(profile);
});

test("an update keeps the library, its edits and its search results", async () => {
  test.skip(process.platform === "darwin", "macOS only notifies: there is no install to test");
  test.skip(!allowed, "Installs the app: set SCENE_ATLAS_UPGRADE_TEST=1 to run it here");
  test.setTimeout(90 * 60_000);

  const oldInstaller = required("UPGRADE_OLD_INSTALLER");
  const fromGitHub = process.env.UPGRADE_FROM_GITHUB === "1";
  const feedDir = fromGitHub ? null : required("UPGRADE_FEED_DIR");
  const newVersion = required("UPGRADE_NEW_VERSION");
  const accept = process.env.ACCEPT_SEARCH_CHANGES === "true";
  const imageDir = ensureTestImages();

  profile = makeProfile(true);
  installDir = path.join(profile.root, "install");
  let exe = await install(oldInstaller, installDir);
  copyInstallerCache(profile.root);

  const modelCache = process.env.UPGRADE_MODEL_CACHE;
  const modelDir = path.join(profile.appData, "models", MODEL);
  if (modelCache && fs.existsSync(path.join(modelCache, MODEL, "version.json"))) {
    fs.cpSync(path.join(modelCache, MODEL), modelDir, { recursive: true });
  }

  feed = feedDir ? await serveFeed(feedDir) : undefined;
  // The updater's download cache lives in the profile, so no earlier run's download is reused.
  // An empty feed override is ignored, so the app reads the GitHub releases.
  const env = { ...isolatedEnv(profile.root), SCENE_ATLAS_UPDATE_FEED: feed?.url ?? "" };

  // ── The old version, with a library ──────────────────────────────────
  const oldApp = await launch(profile, [], { exe, env });
  const oldPage = await waitForBackendUi(oldApp.browser);
  const oldBase = new URL(oldPage.url()).origin;
  const oldState = await updateState(oldPage);
  expect(oldState.mode, "the old install can update itself").toBe("install");
  const oldVersion = oldState.currentVersion;

  await activateSearchModel(oldBase);
  if (modelCache && !fs.existsSync(path.join(modelCache, MODEL, "version.json"))) {
    fs.cpSync(modelDir, path.join(modelCache, MODEL), { recursive: true });
  }
  const edits = await buildLibrary(oldBase, imageDir);

  const beforeIntegrity = await readIntegrity(oldBase);
  expect(missingEdits(edits, beforeIntegrity), "edits made before the update").toEqual([]);
  const specs = planQueries(QUERIES, beforeIntegrity);
  const before = await takeSnapshot(oldBase, oldVersion, beforeIntegrity, specs);

  // ── Update ───────────────────────────────────────────────────────────
  await oldPage.evaluate(() => (window as any).electronAPI.checkForUpdates());
  await expect
    .poll(async () => (await updateState(oldPage)).status, {
      message: "the update to download",
      timeout: 15 * 60_000,
      intervals: [2000],
    })
    .toBe("ready");

  const [oldSidecar] = await sidecars(profile.appData);
  // Doesn't resolve: the app stops its backend and quits into the installer.
  void oldPage.evaluate(() => (window as any).electronAPI.installUpdate()).catch(() => {});
  await waitUntil("the old app to quit", () => !isAlive(oldApp.child.pid!), 60_000);
  if (oldSidecar) await waitUntil("the old backend to stop", () => !isAlive(oldSidecar.pid), 60_000);

  await waitUntil(
    `the installer to finish with version ${newVersion}`,
    async () => {
      if ((await processesMentioning(UPDATER_MARKER)).length > 0) return false;
      const updated = await updatedExecutable(installDir!, exe, newVersion);
      if (updated) exe = updated;
      return updated !== null;
    },
    10 * 60_000,
  );
  // The installer starts the app again on the default profile: not the one under test.
  for (const p of await processesMentioning(installDir)) {
    if (!p.command.includes(profile.userData)) {
      try {
        process.kill(p.pid);
      } catch {
        // Already gone.
      }
    }
  }

  // ── The new version, on the same library ─────────────────────────────
  const newApp = await launch(profile, [], { exe, env });
  const newPage = await waitForBackendUi(newApp.browser);
  const newBase = new URL(newPage.url()).origin;
  expect((await updateState(newPage)).currentVersion).toBe(newVersion);

  const afterIntegrity = await readIntegrity(newBase);
  const after = await takeSnapshot(newBase, newVersion, afterIntegrity, specs);

  // ── Compare and report ───────────────────────────────────────────────
  const comparison = compareSnapshots(specs, before, after);
  const lost = missingEdits(edits, afterIntegrity);
  if (lost.length) comparison.integrityProblems.push(`the update lost ${lost.join(", ")}`);

  const imageNames = Object.fromEntries(
    Object.entries(beforeIntegrity.images).map(([id, image]) => [id, image.name]),
  );
  const groupNames = Object.fromEntries(
    Object.entries(beforeIntegrity.groups).map(([id, group]) => [id, group.name]),
  );
  const differential = !fs
    .readFileSync(path.join(profile.userData, "updater.log"), "utf8")
    .includes("fallback to full download");
  const report =
    renderReport(comparison, {
      fromVersion: oldVersion,
      toVersion: newVersion,
      acceptSearchChanges: accept,
      reason: process.env.SEARCH_CHANGE_REASON,
      imageNames,
      groupNames,
    }) +
    `\n**Download:** ${differential ? "differential" : "full (the differential download failed; see updater.log)"}.\n`;

  fs.mkdirSync(REPORT_DIR, { recursive: true });
  fs.writeFileSync(path.join(REPORT_DIR, "report.md"), report);
  fs.writeFileSync(
    path.join(REPORT_DIR, "snapshots.json"),
    JSON.stringify({ specs, before, after, comparison, feedRequests: feed?.requests ?? "github" }, null, 2),
  );
  if (process.env.GITHUB_STEP_SUMMARY) fs.appendFileSync(process.env.GITHUB_STEP_SUMMARY, report);
  console.log(report);

  expect(comparison.integrityProblems, "library problems (never accepted)").toEqual([]);
  expect(failsRelease(comparison, accept), "search results changed (see report.md)").toBe(false);
});
