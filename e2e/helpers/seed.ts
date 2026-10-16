import crypto from "crypto";
import fs from "fs";
import path from "path";
import { BACKEND_URL } from "./config";
import { listMediaFiles } from "./images";

// Seeds the backend through the import API (ADR-018, design/ingestion.md §7).

const API = `${BACKEND_URL}/api/v1/imports`;
const MANIFEST_CHUNK = 2000;

interface ImportJobDetail {
  status: "active" | "paused" | "completed" | "cancelled";
  counts: Record<"done" | "duplicate" | "failed" | "skipped" | "total", number>;
  group_count: number;
}

interface ManifestItem {
  client_ref: string;
  item_id: number;
  state: string;
}

async function api<T>(
  method: string,
  url: string,
  init: { json?: unknown; bytes?: Buffer } = {},
): Promise<T> {
  const res = await fetch(url, {
    method,
    headers: init.bytes
      ? { "Content-Type": "application/octet-stream" }
      : init.json !== undefined
        ? { "Content-Type": "application/json" }
        : undefined,
    body: init.bytes ? new Uint8Array(init.bytes) : JSON.stringify(init.json),
  });
  if (!res.ok) {
    throw new Error(
      `${method} ${url} failed: ${res.status} ${await res.text()}`,
    );
  }
  return (await res.json()) as T;
}

/**
 * Import every media file under `imageDir` and wait for it to finish. The
 * first 2 are scenes so the scene-type filter tests have data.
 */
export async function seedTestData(imageDir: string): Promise<void> {
  const files = listMediaFiles(imageDir);
  if (files.length === 0) throw new Error(`No images found in ${imageDir}`);
  console.log(`[seed] Importing ${files.length} file(s) from ${imageDir}`);

  const job = await api<{ id: string }>("POST", API, {
    json: { label: "E2E seed", default_image_type: "battlemap" },
  });
  const jobId = job.id;

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
      { json: { files: manifest.slice(i, i + MANIFEST_CHUNK) } },
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
      json: {
        items: waiting.map((it) => ({
          item_id: it.item_id,
          sha256: crypto
            .createHash("sha256")
            .update(fs.readFileSync(byRef.get(it.client_ref)!))
            .digest("hex"),
        })),
      },
    },
  );
  const stillWaiting = new Set(
    hashed.items
      .filter((r) => r.state === "awaiting_bytes")
      .map((r) => r.item_id),
  );

  for (const it of waiting) {
    if (!stillWaiting.has(it.item_id)) continue;
    await api("PUT", `${API}/${jobId}/items/${it.item_id}/content`, {
      bytes: fs.readFileSync(byRef.get(it.client_ref)!),
    });
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
    const failed = await api<{
      items: {
        relative_path: string;
        error_stage: string | null;
        error_reason: string | null;
      }[];
    }>("GET", `${API}/${jobId}/items?state=failed&limit=50`);
    const lines = failed.items.map(
      (f) => `  ${f.relative_path}: [${f.error_stage}] ${f.error_reason}`,
    );
    throw new Error(
      `Seed import ${detail.status} with ${c.failed} failed file(s):\n${lines.join("\n")}`,
    );
  }
}

async function waitForImport(
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
