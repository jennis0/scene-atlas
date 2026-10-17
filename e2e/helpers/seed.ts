import fs from "fs";
import path from "path";
import { BACKEND_URL } from "./config";

/**
 * Seed the backend with test images through the imports API (ADR-018,
 * design/ingestion.md "Upload protocol"):
 *
 *   POST /imports → POST /imports/{id}/manifest (chunks) → POST /imports/{id}/seal
 *   → PUT /imports/{id}/items/{item_id}/content per file → poll GET /imports/{id}
 *
 * Client hashes (POST /hashes) are optional and skipped: the library is empty,
 * and the server deduplicates on receipt anyway.
 */

const IMPORTS = `${BACKEND_URL}/api/v1/imports`;
// Server-side limit per manifest request (MAX_MANIFEST_CHUNK in import_schemas.py).
const MANIFEST_CHUNK = 2000;
// Same as the frontend ImportManager's upload pool.
const UPLOAD_CONCURRENCY = 3;
// The first N files (in sorted path order) are seeded as "scene" so the
// scene-type filter tests have data; the rest are battlemaps.
const SCENE_COUNT = 2;
const POLL_TIMEOUT_MS = 180_000;
const POLL_INTERVAL_MS = 1000;

const MEDIA_RE = /\.(jpe?g|png|webp|gif|mp4|webm)$/i;

type ImageType = "battlemap" | "scene";

interface ImportCounts {
  awaiting_bytes: number;
  ready: number;
  processing: number;
  done: number;
  duplicate: number;
  failed: number;
  skipped: number;
  total: number;
}

interface ImportJobDetail {
  id: string;
  status: "active" | "paused" | "completed" | "cancelled";
  planned: boolean;
  counts: ImportCounts;
  groups: {
    id: number;
    author: string | null;
    group_name: string;
    image_group_id: number | null;
    counts: ImportCounts;
  }[];
}

interface ManifestResponse {
  items: {
    client_ref: string | null;
    item_id: number;
    relative_path: string;
    state: string;
    error_reason: string | null;
  }[];
  ignored: number;
}

interface ContentResult {
  item_id: number;
  state: string;
  error_reason: string | null;
}

interface QueueStatus {
  running: boolean;
  system_paused: boolean;
  reason: string | null;
}

interface ImportItemPage {
  items: {
    relative_path: string;
    state: string;
    error_stage: string | null;
    error_reason: string | null;
  }[];
}

/**
 * Import every media file under `imageDir` and wait until processing finishes.
 * Paths are sent relative to `imageDir`, so the folder layout drives the
 * author/group parsing exactly as it would for a user's upload.
 */
export async function seedTestData(imageDir: string): Promise<void> {
  console.log("[seed] Starting test data seed...");

  const files = collectFiles(imageDir).sort();
  if (files.length === 0) throw new Error(`No images found in ${imageDir}`);
  console.log(`[seed] Found ${files.length} file(s) in ${imageDir}`);

  // 1. Create the job
  const job = await api<{ id: string }>("POST", IMPORTS, {
    label: "E2E seed",
    default_image_type: "battlemap",
  });
  const jobId = job.id;
  console.log(`[seed] Job created: ${jobId}`);

  try {
    // 2. Describe the files (metadata only)
    const byRef = new Map<string, string>(); // client_ref → absolute path
    const items: { itemId: number; filePath: string }[] = [];
    for (let start = 0; start < files.length; start += MANIFEST_CHUNK) {
      const chunk = files
        .slice(start, start + MANIFEST_CHUNK)
        .map((filePath, i) => {
          const index = start + i;
          const ref = String(index);
          byRef.set(ref, filePath);
          const stat = fs.statSync(filePath);
          const imageType: ImageType =
            index < SCENE_COUNT ? "scene" : "battlemap";
          return {
            client_ref: ref,
            relative_path: path
              .relative(imageDir, filePath)
              .replace(/\\/g, "/"),
            size: stat.size,
            last_modified: Math.round(stat.mtimeMs),
            image_type: imageType,
          };
        });
      const res = await api<ManifestResponse>(
        "POST",
        `${IMPORTS}/${jobId}/manifest`,
        {
          files: chunk,
        },
      );
      for (const item of res.items) {
        const filePath =
          item.client_ref == null ? undefined : byRef.get(item.client_ref);
        if (item.state === "awaiting_bytes" && filePath) {
          items.push({ itemId: item.item_id, filePath });
        } else {
          console.warn(
            `[seed]   Not uploading ${item.relative_path}: ${item.state}` +
              (item.error_reason ? ` (${item.error_reason})` : ""),
          );
        }
      }
      if (res.ignored)
        console.log(`[seed]   ${res.ignored} file(s) ignored by the server`);
    }
    console.log(`[seed] Manifest accepted: ${items.length} file(s) to upload`);

    // 3. Seal: the server groups the paths and the worker starts on items as bytes arrive
    const sealed = await api<ImportJobDetail>(
      "POST",
      `${IMPORTS}/${jobId}/seal`,
    );
    console.log(`[seed] Sealed: ${sealed.groups.length} group(s)`);
    for (const g of sealed.groups) {
      console.log(
        `[seed]   Group "${g.group_name}" by ${g.author ?? "(none)"}: ${g.counts.total} file(s)`,
      );
    }

    // 4. Upload bytes, a few files at a time
    let next = 0;
    const uploadWorker = async () => {
      while (next < items.length) {
        const { itemId, filePath } = items[next++];
        const result = await api<ContentResult>(
          "PUT",
          `${IMPORTS}/${jobId}/items/${itemId}/content`,
          new Uint8Array(fs.readFileSync(filePath)),
        );
        if (result.state !== "ready" && result.state !== "duplicate") {
          console.warn(
            `[seed]   Upload of ${path.basename(filePath)} ended in ${result.state}` +
              (result.error_reason ? `: ${result.error_reason}` : ""),
          );
        }
      }
    };
    await Promise.all(Array.from({ length: UPLOAD_CONCURRENCY }, uploadWorker));
    console.log("[seed] Upload complete. Waiting for processing...");
  } catch (err) {
    // Don't leave a half-set-up job active (mirrors the frontend's behaviour).
    await fetch(`${IMPORTS}/${jobId}/cancel`, { method: "POST" }).catch(
      () => undefined,
    );
    throw err;
  }

  // 5. Poll until the job completes (a job never "fails"; outcomes are counts)
  const final = await waitForCompletion(jobId);
  const c = final.counts;
  console.log(
    `[seed] Job completed: ${c.done} done, ${c.duplicate} duplicate, ` +
      `${c.failed} failed, ${c.skipped} skipped (of ${c.total})`,
  );
  for (const g of final.groups) {
    console.log(
      `[seed]   Group "${g.group_name}": done=${g.counts.done}, failed=${g.counts.failed}, ` +
        `duplicate=${g.counts.duplicate}`,
    );
  }
  if (c.failed > 0) {
    const failed = await api<ImportItemPage>(
      "GET",
      `${IMPORTS}/${jobId}/items?state=failed&limit=50`,
    );
    for (const item of failed.items) {
      console.warn(
        `[seed]   FAILED ${item.relative_path} [${item.error_stage}]: ${item.error_reason}`,
      );
    }
  }
  if (c.done === 0) {
    throw new Error(
      `Import ${jobId} completed without importing any file: ${JSON.stringify(c)}`,
    );
  }
  console.log("[seed] Seed complete.");
}

async function waitForCompletion(jobId: string): Promise<ImportJobDetail> {
  const deadline = Date.now() + POLL_TIMEOUT_MS;
  let last = "";
  let detail: ImportJobDetail | undefined;
  while (Date.now() < deadline) {
    detail = await api<ImportJobDetail>("GET", `${IMPORTS}/${jobId}`);
    const c = detail.counts;
    const summary = `${detail.status} (ready=${c.ready}, processing=${c.processing}, done=${c.done}, failed=${c.failed})`;
    if (summary !== last) {
      console.log(`[seed]   Job status: ${summary}`);
      last = summary;
    }
    if (detail.status === "completed") return detail;
    if (detail.status === "cancelled") {
      throw new Error(`Import ${jobId} was cancelled: ${JSON.stringify(c)}`);
    }
    await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));
  }
  // Explain the most likely cause of a stall: the queue is paused for a system
  // reason (no AI model, library folder missing, disk full).
  const queue = await api<{ queue: QueueStatus }>("GET", IMPORTS)
    .then((r) => r.queue)
    .catch(() => undefined);
  throw new Error(
    `Import ${jobId} did not complete within ${POLL_TIMEOUT_MS}ms. ` +
      `Last state: ${JSON.stringify(detail?.counts)}; queue: ${JSON.stringify(queue)}`,
  );
}

/** JSON request helper: object bodies are sent as JSON, byte bodies raw. */
async function api<T>(
  method: string,
  url: string,
  body?: object | Uint8Array<ArrayBuffer>,
): Promise<T> {
  const init: RequestInit = { method };
  if (body instanceof Uint8Array) {
    init.body = body;
    init.headers = { "Content-Type": "application/octet-stream" };
  } else if (body !== undefined) {
    init.body = JSON.stringify(body);
    init.headers = { "Content-Type": "application/json" };
  }
  const res = await fetch(url, init);
  if (!res.ok) {
    throw new Error(
      `${method} ${url} failed: ${res.status} ${await res.text()}`,
    );
  }
  return (await res.json()) as T;
}

/** Collect all supported media files recursively from a directory. */
function collectFiles(dir: string): string[] {
  const results: string[] = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      results.push(...collectFiles(full));
    } else if (MEDIA_RE.test(entry.name)) {
      results.push(full);
    }
  }
  return results;
}
