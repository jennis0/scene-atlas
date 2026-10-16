import crypto from "crypto";
import fs from "fs";
import path from "path";
import { BACKEND_URL } from "./config";

/**
 * Seeds the backend through the import API (ADR-018, design/ingest-redesign.md §7):
 * create job → manifest → seal → hashes → PUT bytes per item → poll until finished.
 */

const API = `${BACKEND_URL}/api/v1/imports`;
const MANIFEST_CHUNK = 2000;

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
  counts: ImportCounts;
  group_count: number;
  groups: { group_name: string; counts: ImportCounts }[];
}

interface ManifestItem {
  client_ref: string | null;
  item_id: number;
  relative_path: string;
  state: string;
  error_reason: string | null;
}

interface ImportItem {
  id: number;
  relative_path: string;
  state: string;
  error_stage: string | null;
  error_reason: string | null;
}

async function api<T>(
  method: string,
  url: string,
  body?: unknown,
  raw?: Buffer,
): Promise<T> {
  const res = await fetch(url, {
    method,
    headers: raw
      ? { "Content-Type": "application/octet-stream" }
      : body !== undefined
        ? { "Content-Type": "application/json" }
        : undefined,
    body: raw
      ? new Uint8Array(raw)
      : body !== undefined
        ? JSON.stringify(body)
        : undefined,
  });
  if (!res.ok) {
    throw new Error(
      `${method} ${url} failed: ${res.status} ${await res.text()}`,
    );
  }
  return (await res.json()) as T;
}

/**
 * Import every media file under `imageDir` and wait for the job to finish.
 * The first 2 files are imported as "scene" (so scene-type filter tests have
 * data); the rest as "battlemap". Throws if any file fails.
 */
export async function seedTestData(imageDir: string): Promise<void> {
  const files = collectFiles(imageDir);
  if (files.length === 0) throw new Error(`No images found in ${imageDir}`);
  console.log(`[seed] Importing ${files.length} file(s) from ${imageDir}`);

  const job = await api<{ id: string }>("POST", API, {
    label: "E2E seed",
    default_image_type: "battlemap",
  });
  const jobId = job.id;

  // Manifest: metadata only. client_ref maps results back to local paths.
  const byRef = new Map<string, string>();
  const manifest = files.map((file, i) => {
    const stat = fs.statSync(file);
    const ref = String(i);
    byRef.set(ref, file);
    return {
      client_ref: ref,
      relative_path: path.relative(imageDir, file).replace(/\\/g, "/"),
      size: stat.size,
      last_modified: Math.round(stat.mtimeMs),
      image_type: i < 2 ? "scene" : "battlemap",
    };
  });
  const items: ManifestItem[] = [];
  for (let i = 0; i < manifest.length; i += MANIFEST_CHUNK) {
    const res = await api<{ items: ManifestItem[]; ignored: number }>(
      "POST",
      `${API}/${jobId}/manifest`,
      { files: manifest.slice(i, i + MANIFEST_CHUNK) },
    );
    items.push(...res.items);
  }

  await api("POST", `${API}/${jobId}/seal`);

  // Send hashes first so files already in the library are skipped without upload.
  const waiting = items.filter((it) => it.state === "awaiting_bytes");
  const hashed = await api<{ items: { item_id: number; state: string }[] }>(
    "POST",
    `${API}/${jobId}/hashes`,
    {
      items: waiting.map((it) => ({
        item_id: it.item_id,
        sha256: crypto
          .createHash("sha256")
          .update(fs.readFileSync(byRef.get(it.client_ref!)!))
          .digest("hex"),
      })),
    },
  );
  const stillWaiting = new Set(
    hashed.items
      .filter((r) => r.state === "awaiting_bytes")
      .map((r) => r.item_id),
  );

  for (const it of waiting) {
    if (!stillWaiting.has(it.item_id)) continue;
    await api(
      "PUT",
      `${API}/${jobId}/items/${it.item_id}/content`,
      undefined,
      fs.readFileSync(byRef.get(it.client_ref!)!),
    );
  }
  console.log(
    `[seed] Sent ${stillWaiting.size} file(s); waiting for processing`,
  );

  const detail = await waitForImport(jobId, 300_000);
  const c = detail.counts;
  console.log(
    `[seed] Import ${detail.status}: ${c.done} done, ${c.duplicate} duplicate, ` +
      `${c.failed} failed, ${c.skipped} skipped, ${detail.group_count} group(s)`,
  );
  if (detail.status !== "completed" || c.failed > 0) {
    const failed = await api<{ items: ImportItem[] }>(
      "GET",
      `${API}/${jobId}/items?state=failed&limit=50`,
    );
    const lines = failed.items.map(
      (f) => `  ${f.relative_path}: [${f.error_stage}] ${f.error_reason}`,
    );
    throw new Error(
      `Seed import ${detail.status} with ${c.failed} failed file(s):\n${lines.join("\n")}`,
    );
  }
}

/** Poll an import until it is completed or cancelled. */
export async function waitForImport(
  jobId: string,
  timeoutMs: number,
): Promise<ImportJobDetail> {
  const deadline = Date.now() + timeoutMs;
  let last = "";
  while (Date.now() < deadline) {
    const detail = await api<ImportJobDetail>("GET", `${API}/${jobId}`);
    const c = detail.counts;
    const line = `${detail.status} ${c.done + c.duplicate + c.failed + c.skipped}/${c.total}`;
    if (line !== last) console.log(`[seed]   ${line}`);
    last = line;
    if (detail.status === "completed" || detail.status === "cancelled") {
      return detail;
    }
    await new Promise((r) => setTimeout(r, 1000));
  }
  throw new Error(
    `Import ${jobId} did not finish within ${timeoutMs}ms (${last})`,
  );
}

/** Collect all supported media files recursively, in a stable order. */
function collectFiles(dir: string): string[] {
  const results: string[] = [];
  const entries = fs
    .readdirSync(dir, { withFileTypes: true })
    .sort((a, b) => a.name.localeCompare(b.name));
  for (const entry of entries) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      results.push(...collectFiles(full));
    } else if (/\.(jpe?g|png|webp|mp4|webm)$/i.test(entry.name)) {
      results.push(full);
    }
  }
  return results;
}
