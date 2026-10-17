import fs from "fs";
import path from "path";

/**
 * Per-run isolated backend storage for E2E runs.
 *
 * The backend reads its storage roots from APP_DATA_DIR and IMAGE_LIBRARY_DIR
 * (backend/app/config.py). Without them it falls back to the repo's ./data and
 * ./images, i.e. a developer's real library, so E2E must always set both.
 *
 * The Playwright main process creates a fresh `e2e/.tmp-data/run-XXXXXX/` per
 * run and exports the variables into its own environment; the backend
 * webServer, the worker processes and anything they spawn (e.g.
 * scripts/models/setup_models.py) inherit them. Workers re-evaluate the config,
 * see E2E_RUN_DIR already set and reuse the same directory.
 *
 * The previous run's directory is kept for post-mortem debugging and removed
 * at the start of the next run.
 *
 * Models are a download cache, not library state: `<run>/data/models` is a
 * link to E2E_MODELS_DIR (default: the repo's data/models, which is where CI
 * caches the ONNX model), so runs don't re-download ~250 MB.
 */

const E2E_DIR = path.resolve(__dirname, "..");
const REPO_ROOT = path.resolve(E2E_DIR, "..");
const RUNS_ROOT = path.join(E2E_DIR, ".tmp-data");

export interface IsolatedRun {
  runDir: string;
  appDataDir: string;
  imageLibraryDir: string;
}

export function prepareIsolatedRun(): IsolatedRun {
  let runDir = process.env.E2E_RUN_DIR;
  if (!runDir) {
    fs.mkdirSync(RUNS_ROOT, { recursive: true });
    removePreviousRuns();
    runDir = fs.mkdtempSync(path.join(RUNS_ROOT, "run-"));
    process.env.E2E_RUN_DIR = runDir;
  }

  const appDataDir = path.join(runDir, "data");
  const imageLibraryDir = path.join(runDir, "images");
  fs.mkdirSync(appDataDir, { recursive: true });
  fs.mkdirSync(imageLibraryDir, { recursive: true });
  linkModels(path.join(appDataDir, "models"));

  // Override anything inherited from the shell or loaded from ../.env.
  process.env.APP_DATA_DIR = appDataDir;
  process.env.IMAGE_LIBRARY_DIR = imageLibraryDir;
  return { runDir, appDataDir, imageLibraryDir };
}

function removePreviousRuns(): void {
  for (const entry of fs.readdirSync(RUNS_ROOT)) {
    if (!entry.startsWith("run-")) continue;
    try {
      fs.rmSync(path.join(RUNS_ROOT, entry), { recursive: true, force: true });
    } catch (err) {
      console.warn(`[e2e] Could not remove old run directory ${entry}: ${err}`);
    }
  }
}

function linkModels(dest: string): void {
  if (fs.existsSync(dest)) return;
  const source = path.resolve(
    process.env.E2E_MODELS_DIR ?? path.join(REPO_ROOT, "data", "models"),
  );
  fs.mkdirSync(source, { recursive: true });
  // "junction" lets Windows link a directory without admin rights; ignored elsewhere.
  fs.symlinkSync(source, dest, "junction");
}
