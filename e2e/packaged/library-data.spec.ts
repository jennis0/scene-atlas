/**
 * The packaged desktop app moving, exporting and rebuilding a library with its real backend
 * and real restarts (design/export-backup-move.md §7, §8, §10): what the backend's
 * integration tests can only simulate. A release gate on Windows, like lifecycle.spec.ts.
 *
 * The images are made here (small PNGs), so no fixture key is needed. The search model
 * is needed to import them: it's downloaded the first time, or copied from
 * PACKAGED_MODEL_CACHE (or UPGRADE_MODEL_CACHE), a folder that keeps it between runs.
 *
 * Run after a build: npm run test:packaged (design/testing.md#packaged-app-tests).
 */
import { expect, test, type Page } from "@playwright/test";
import fs from "fs";
import path from "path";
import zlib from "zlib";
import { tokenHeader } from "../helpers/appToken";
import { seedTestData } from "../helpers/seed";
import { activateSearchModel, readIntegrity } from "../upgrade/library";
import {
  cleanUp,
  launch,
  makeProfile,
  readConfig,
  sidecars,
  waitForBackendUi,
  waitForLoadingPage,
  waitForRestartedUi,
  waitUntil,
  type Profile,
  type RunningApp,
} from "./app";

const MODEL = "small";
let profile: Profile;

test.afterEach(async () => {
  if (profile) await cleanUp(profile);
});

// ── Helpers ────────────────────────────────────────────────────────────────

function crc32(buf: Buffer): number {
  let c = ~0;
  for (const byte of buf) {
    c ^= byte;
    for (let k = 0; k < 8; k++) c = (c >>> 1) ^ (0xedb88320 & -(c & 1));
  }
  return ~c >>> 0;
}

function chunk(type: string, data: Buffer): Buffer {
  const len = Buffer.alloc(4);
  len.writeUInt32BE(data.length);
  const body = Buffer.concat([Buffer.from(type, "ascii"), data]);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(body));
  return Buffer.concat([len, body, crc]);
}

/** A *size*×*size* PNG, a different gradient for each *seed*, so no two are duplicates. */
function png(seed: number, size = 96): Buffer {
  const rows: Buffer[] = [];
  for (let y = 0; y < size; y++) {
    const row = Buffer.alloc(1 + size * 3);
    for (let x = 0; x < size; x++) {
      row[1 + x * 3] = (x * 3 + seed * 41) & 255;
      row[2 + x * 3] = (y * 5 + seed * 17) & 255;
      row[3 + x * 3] = ((x ^ y) + seed * 73) & 255;
    }
    rows.push(row);
  }
  const header = Buffer.alloc(13);
  header.writeUInt32BE(size, 0);
  header.writeUInt32BE(size, 4);
  header.set([8, 2, 0, 0, 0], 8); // 8-bit RGB
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk("IHDR", header),
    chunk("IDAT", zlib.deflateSync(Buffer.concat(rows))),
    chunk("IEND", Buffer.alloc(0)),
  ]);
}

/** A folder of test maps: two groups of variants and a loner. */
function makeImages(root: string): string {
  const dir = path.join(root, "test-images");
  const files = [
    "Czepeku/Golden Forest/Golden Forest Day.png",
    "Czepeku/Golden Forest/Golden Forest Night.png",
    "Czepeku/Golden Forest/Golden Forest Winter.png",
    "Tom/Harbour/Harbour Dawn.png",
    "Tom/Harbour/Harbour Storm.png",
    "Lone Tower.png",
  ];
  files.forEach((rel, i) => {
    const file = path.join(dir, rel);
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.writeFileSync(file, png(i + 1));
  });
  return dir;
}

function modelCache(): string | undefined {
  return process.env.PACKAGED_MODEL_CACHE ?? process.env.UPGRADE_MODEL_CACHE;
}

/** Copy a cached model into app data before the first launch. */
function seedModel(appData: string): void {
  const cache = modelCache();
  if (cache && fs.existsSync(path.join(cache, MODEL, "version.json"))) {
    fs.cpSync(path.join(cache, MODEL), path.join(appData, "models", MODEL), {
      recursive: true,
    });
  }
}

function keepModel(appData: string): void {
  const cache = modelCache();
  if (cache && !fs.existsSync(path.join(cache, MODEL, "version.json"))) {
    fs.cpSync(path.join(appData, "models", MODEL), path.join(cache, MODEL), {
      recursive: true,
    });
  }
}

async function call<T>(
  base: string,
  method: string,
  route: string,
  body?: unknown,
): Promise<T> {
  const raw = body instanceof Buffer;
  const res = await fetch(`${base}/api/v1${route}`, {
    method,
    headers: {
      ...tokenHeader(),
      ...(body === undefined
        ? {}
        : {
            "Content-Type": raw
              ? "application/octet-stream"
              : "application/json",
          }),
    },
    body:
      body === undefined
        ? undefined
        : raw
          ? new Uint8Array(body)
          : JSON.stringify(body),
  });
  if (!res.ok)
    throw new Error(
      `${method} ${route} failed: ${res.status} ${await res.text()}`,
    );
  return (await res.json()) as T;
}

/** A background job's result, once it has finished. */
async function job<T = Record<string, unknown>>(
  base: string,
  jobId: string,
  timeoutMs = 300_000,
): Promise<T> {
  let last: { status: string; result: T; error: string | null } | undefined;
  await waitUntil(
    `job ${jobId}`,
    async () => {
      last = await call(base, "GET", `/jobs/${jobId}`);
      return last!.status === "completed" || last!.status === "failed";
    },
    timeoutMs,
  );
  if (last!.status === "failed")
    throw new Error(`job ${jobId} failed: ${last!.error}`);
  return last!.result;
}

interface Library {
  app: RunningApp;
  page: Page;
  base: string;
}

/** The app on a seeded profile, with the test maps imported and searchable. */
async function libraryWithMaps(): Promise<Library> {
  profile = makeProfile(true);
  fs.mkdirSync(profile.appData, { recursive: true });
  seedModel(profile.appData);
  const app = await launch(profile);
  const page = await waitForBackendUi(app.browser);
  const base = new URL(page.url()).origin;
  await activateSearchModel(base);
  keepModel(profile.appData);
  await call(base, "POST", "/models/setup-complete");
  await seedTestData(makeImages(profile.root), base);
  return { app, page, base };
}

/**
 * What a move or a rebuild must keep: each image's name, author, grid and tags, its group
 * (by id: they keep their ids; *byId* false for a re-import, which makes new ones), and
 * readable files.
 */
async function contents(base: string, byId = true) {
  const integrity = await readIntegrity(base);
  return {
    images: Object.values(integrity.images)
      .map((i) =>
        [
          i.name,
          i.author,
          byId ? i.group_id : "",
          i.gridded,
          i.grid_width,
          i.tags.join(","),
        ].join(" | "),
      )
      .sort(),
    groups: integrity.groupCount,
    unreadable: integrity.unreadable,
  };
}

async function sidecarPid(appData: string): Promise<number> {
  const [sidecar] = await sidecars(appData);
  expect(sidecar, `a backend on ${appData}`).toBeDefined();
  return sidecar.pid;
}

/** Copy a folder to *target* with the backend's move job, then restart onto it. */
async function move(
  lib: Library,
  kind: "app_data" | "store",
  target: string,
  appData: string,
): Promise<string> {
  const { job_id } = await call<{ job_id: string }>(
    lib.base,
    "POST",
    "/library/move",
    { [kind]: target },
  );
  const copied = await job(lib.base, job_id);
  expect(copied).toEqual({ [kind]: target });
  const status = await call<{ copied: unknown }>(
    lib.base,
    "GET",
    "/library/move",
  );
  expect(status.copied, "Settings offers the restart").toEqual(copied);
  const old = await sidecarPid(appData);
  void lib.page
    .evaluate((m) => (window as any).electronAPI.applyMove(m), copied)
    .catch(() => {}); // never settles: the page reloads
  return waitForRestartedUi(lib.page, old);
}

// ── Tests ──────────────────────────────────────────────────────────────────

test("moving Imported images, then Search data, keeps the library and retires the old folders", async () => {
  const lib = await libraryWithMaps();
  const before = await contents(lib.base);
  expect(before.images).toHaveLength(6);

  const newImages = path.join(profile.root, "moved-images");
  lib.base = await move(lib, "store", newImages, profile.appData);
  expect(readConfig(profile)).toMatchObject({ imageLibraryDir: newImages });
  expect(readConfig(profile).pendingMove).toBeUndefined();
  expect(await contents(lib.base)).toEqual(before);
  expect(
    fs.existsSync(path.join(profile.images, "scene-atlas-moved.txt")),
  ).toBe(true);

  const newData = path.join(profile.root, "moved-app-data");
  lib.base = await move(lib, "app_data", newData, profile.appData);
  expect(readConfig(profile)).toMatchObject({
    appDataDir: newData,
    imageLibraryDir: newImages,
  });
  expect(await sidecars(newData)).toHaveLength(1);
  expect(await contents(lib.base)).toEqual(before);
  // The vectors came too: a search still finds the maps
  const found = await call<{ images: unknown[] }>(
    lib.base,
    "GET",
    "/search/?query=forest&semantic_only=true&limit=10",
  );
  expect(found.images.length).toBeGreaterThan(0);

  // Delete the old copy: only Search data's is recorded by now
  const status = await call<{ moved_from: Record<string, string> }>(
    lib.base,
    "GET",
    "/library/move",
  );
  expect(status.moved_from).toEqual({ app_data: profile.appData });
  const deleted = await call<{ deleted: number; kept: string[] }>(
    lib.base,
    "DELETE",
    "/library/move/old",
  );
  expect(deleted).toEqual({ deleted: 1, kept: [] });
  expect(fs.existsSync(profile.appData)).toBe(false);
});

test("a move whose finish fails goes back to the old folders, unchanged", async () => {
  const lib = await libraryWithMaps();
  const before = await contents(lib.base);
  const newImages = path.join(profile.root, "moved-images");
  const { job_id } = await call<{ job_id: string }>(
    lib.base,
    "POST",
    "/library/move",
    { store: newImages },
  );
  const copied = await job(lib.base, job_id);
  // A file added to the old store since the copy, whose place in the new one is taken
  // by a folder: copying it at the finish fails
  const shard = path.join("zz", "zz", "zzzz-after-copy.png");
  fs.mkdirSync(path.dirname(path.join(profile.images, shard)), {
    recursive: true,
  });
  fs.writeFileSync(path.join(profile.images, shard), png(99));
  fs.mkdirSync(path.join(newImages, shard), { recursive: true });

  const old = await sidecarPid(profile.appData);
  void lib.page
    .evaluate((m) => (window as any).electronAPI.applyMove(m), copied)
    .catch(() => {});
  lib.base = await waitForRestartedUi(lib.page, old);

  expect(readConfig(profile)).toMatchObject({
    appDataDir: profile.appData,
    imageLibraryDir: profile.images,
  });
  expect(readConfig(profile).pendingMove).toBeUndefined();
  expect(await contents(lib.base)).toEqual(before);
  expect(
    fs.existsSync(path.join(profile.images, "scene-atlas-moved.txt")),
  ).toBe(false);
  expect(
    fs.existsSync(path.join(profile.images, "scene-atlas-library.json")),
  ).toBe(true);
});

test("rebuilding from a metadata export undoes later changes, across a restart", async () => {
  const lib = await libraryWithMaps();
  const before = await contents(lib.base);
  const exportFile = path.join(profile.root, "backup.jsonl.gz");
  const started = await call<{ job_id: string }>(
    lib.base,
    "POST",
    "/library/metadata-export",
    { path: exportFile },
  );
  await job(lib.base, started.job_id);

  // A change after the backup
  const [first] = await call<{ id: number }[]>(
    lib.base,
    "GET",
    "/images/?limit=1",
  );
  await call(lib.base, "PATCH", `/images/${first.id}`, {
    name: "Renamed since",
  });
  expect(await contents(lib.base)).not.toEqual(before);

  await call(
    lib.base,
    "PUT",
    "/library/rebuild/upload",
    fs.readFileSync(exportFile),
  );
  const check = await job<{
    missing: { images: number };
    lost: { images: number };
  }>(
    lib.base,
    (
      await call<{ job_id: string }>(
        lib.base,
        "POST",
        "/library/rebuild/check",
        {},
      )
    ).job_id,
  );
  expect(check.missing.images).toBe(0);
  expect(check.lost.images).toBe(0);
  await job(
    lib.base,
    (
      await call<{ job_id: string }>(
        lib.base,
        "POST",
        "/library/rebuild/build",
        {},
      )
    ).job_id,
  );
  expect(await call(lib.base, "POST", "/library/rebuild/apply", {})).toEqual({
    restart: "app",
  });

  const old = await sidecarPid(profile.appData);
  void lib.page
    .evaluate(() => (window as any).electronAPI.restartBackend())
    .catch(() => {});
  lib.base = await waitForRestartedUi(lib.page, old);
  expect(await contents(lib.base)).toEqual(before);
});

test("when Search data is lost, the loading page offers to rebuild, and a staged export is rebuilt at launch", async () => {
  const lib = await libraryWithMaps();
  const before = await contents(lib.base);
  const exportFile = path.join(profile.root, "backup.jsonl.gz");
  await job(
    lib.base,
    (
      await call<{ job_id: string }>(
        lib.base,
        "POST",
        "/library/metadata-export",
        {
          path: exportFile,
        },
      )
    ).job_id,
  );
  // Quit, and lose the app data (but keep the model, which isn't in an export)
  lib.app.child.kill();
  await waitUntil(
    "the app and its backend to exit",
    async () => (await sidecars(profile.appData)).length === 0,
    60_000,
  );
  const models = path.join(profile.root, "models-kept");
  fs.cpSync(path.join(profile.appData, "models"), models, { recursive: true });
  fs.rmSync(profile.appData, { recursive: true, force: true });
  fs.mkdirSync(profile.appData);

  // The refusal: the loading page offers Rebuild from export… (its picker is native)
  const refused = await launch(profile);
  const loading = await waitForLoadingPage(refused.browser);
  await expect(
    loading.getByRole("button", { name: "Rebuild from export…" }),
  ).toBeVisible({ timeout: 120_000 });
  refused.child.kill();
  await waitUntil(
    "the refused app to exit",
    async () => (await sidecars(profile.appData)).length === 0,
    60_000,
  );

  // What the button does, then a launch: the export staged where the backend looks
  fs.mkdirSync(path.join(profile.appData, "rebuild"), { recursive: true });
  fs.copyFileSync(
    exportFile,
    path.join(profile.appData, "rebuild", "staged.jsonl"),
  );
  fs.cpSync(models, path.join(profile.appData, "models"), { recursive: true });
  const rebuilt = await launch(profile);
  const page = await waitForBackendUi(rebuilt.browser);
  const base = new URL(page.url()).origin;
  await activateSearchModel(base);
  expect((await contents(base)).images).toEqual(before.images);
  // The thumbnails are made again after startup
  await waitUntil(
    "the thumbnails to be made again",
    async () => (await contents(base)).unreadable.length === 0,
    300_000,
  );
});

test("the full library export re-imports as the library it came from", async () => {
  const lib = await libraryWithMaps();
  const before = await contents(lib.base, false);
  const folder = path.join(profile.root, "Export");
  fs.mkdirSync(folder);
  const started = await call<{ job_id: string }>(
    lib.base,
    "POST",
    "/library/full-export",
    { path: folder },
  );
  const result = await job<{ images: number; skipped: number }>(
    lib.base,
    started.job_id,
  );
  expect(result).toMatchObject({ images: 6, skipped: 0 });
  expect(fs.existsSync(path.join(folder, "scene-atlas.jsonl"))).toBe(true);

  const purge = await call<{ job_id: string }>(
    lib.base,
    "DELETE",
    "/system/library",
  );
  await job(lib.base, purge.job_id);
  expect((await contents(lib.base, false)).images).toHaveLength(0);

  // Back in through the desktop app's folder import
  const imp = await call<{ id: string }>(lib.base, "POST", "/imports", {
    label: "Back",
    default_image_type: "battlemap",
  });
  await call(lib.base, "POST", `/imports/${imp.id}/local-sources`, {
    paths: [folder],
  });
  await call(lib.base, "POST", `/imports/${imp.id}/seal`);
  await waitUntil(
    "the export to import",
    async () =>
      (await call<{ status: string }>(lib.base, "GET", `/imports/${imp.id}`))
        .status === "completed",
    300_000,
  );
  expect(await contents(lib.base, false)).toEqual(before);
});
