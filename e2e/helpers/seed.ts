import fs from "fs";
import path from "path";
import { BACKEND_URL } from "./config";

interface ImportFileInfo {
  relative_path: string;
  filename: string;
  name: string | null;
  image_type: string | null;
  gridded: boolean | null;
  subgroup: string | null;
  content_hash: string | null;
  detected_tags: { category: string; value: string }[];
}

interface ImportGroup {
  author: string | null;
  group_name: string;
  files: ImportFileInfo[];
}

interface AnalyseResponse {
  job_id: string;
  total_files: number;
  groups: ImportGroup[];
}

/**
 * Seed the backend with test images via the import API.
 * Uploads images, analyses, confirms all groups, and waits for processing to complete.
 */
export async function seedTestData(imageDir: string): Promise<void> {
  console.log("[seed] Starting test data seed...");

  // 1. Init an import job
  console.log("[seed] Step 1: Initialising import job...");
  const initRes = await fetch(`${BACKEND_URL}/api/v1/imports/init`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: "{}",
  });
  if (!initRes.ok) {
    const body = await initRes.text();
    throw new Error(`Failed to init import: ${initRes.status} ${body}`);
  }
  const { job_id: jobId } = (await initRes.json()) as { job_id: string };
  console.log(`[seed] Job created: ${jobId}`);

  // 2. Collect all image files
  const files = collectFiles(imageDir);
  if (files.length === 0) throw new Error(`No images found in ${imageDir}`);
  console.log(`[seed] Step 2: Found ${files.length} image(s) in ${imageDir}`);

  // 3. Upload files via upload-batch
  console.log(`[seed] Step 3: Uploading ${files.length} file(s)...`);
  const form = new FormData();
  const relativePaths: string[] = [];
  for (const filePath of files) {
    const relativePath = path.relative(imageDir, filePath).replace(/\\/g, "/");
    relativePaths.push(relativePath);
    const buffer = fs.readFileSync(filePath);
    const ext = path.extname(filePath).toLowerCase();
    const mimeTypes: Record<string, string> = {
      ".jpg": "image/jpeg",
      ".jpeg": "image/jpeg",
      ".png": "image/png",
      ".webp": "image/webp",
      ".gif": "image/gif",
      ".mp4": "video/mp4",
      ".webm": "video/webm",
    };
    const blob = new Blob([buffer], {
      type: mimeTypes[ext] || "application/octet-stream",
    });
    form.append("files", blob, path.basename(filePath));
  }
  form.append("relative_paths", JSON.stringify(relativePaths));

  const uploadRes = await fetch(
    `${BACKEND_URL}/api/v1/imports/${jobId}/upload-batch`,
    {
      method: "POST",
      body: form,
    },
  );
  if (!uploadRes.ok) {
    const body = await uploadRes.text();
    throw new Error(`Upload failed: ${uploadRes.status} ${body}`);
  }
  console.log("[seed] Upload complete.");

  // 4. Analyse staged files
  console.log("[seed] Step 4: Analysing staged files...");
  const analyseRes = await fetch(
    `${BACKEND_URL}/api/v1/imports/${jobId}/analyse`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ manifest: [], image_type: "battlemap" }),
    },
  );
  if (!analyseRes.ok) {
    const body = await analyseRes.text();
    throw new Error(`Analyse failed: ${analyseRes.status} ${body}`);
  }
  const analyseData = (await analyseRes.json()) as AnalyseResponse;
  console.log(
    `[seed] Analysis complete: ${analyseData.groups.length} group(s), ` +
      `${analyseData.total_files} total file(s)`,
  );
  for (const g of analyseData.groups) {
    console.log(`[seed]   Group "${g.group_name}": ${g.files.length} file(s)`);
  }

  // 5. Build confirm-all payload from the analysis
  console.log("[seed] Step 5: Confirming all groups...");
  const confirmGroups = analyseData.groups.map((group) => ({
    author: group.author || "TestArtist",
    group_name: group.group_name,
    files: group.files.map((f) => ({
      relative_path: f.relative_path,
      name: f.name,
      image_type: f.image_type,
      gridded: f.gridded,
      subgroup: f.subgroup,
      content_hash: f.content_hash,
      tags: f.detected_tags || [],
    })),
    remaining_groups: [],
  }));

  const confirmRes = await fetch(
    `${BACKEND_URL}/api/v1/imports/${jobId}/confirm-all`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ groups: confirmGroups }),
    },
  );
  if (!confirmRes.ok) {
    const body = await confirmRes.text();
    throw new Error(`Confirm failed: ${confirmRes.status} ${body}`);
  }
  console.log("[seed] Confirm accepted. Processing pipeline running...");

  // 6. Poll until processing completes
  console.log("[seed] Step 6: Polling for job completion...");
  let lastStatus = "";
  let finalStatusData: Record<string, unknown> = {};
  await pollUntil(
    async () => {
      const res = await fetch(`${BACKEND_URL}/api/v1/imports/${jobId}/status`);
      const data = (await res.json()) as {
        status: string;
        completed_groups?: number;
        total_groups?: number;
        failed_groups?: number;
        processed_files?: number;
        failed_files?: number;
        groups?: {
          group_id: number | null;
          group_name: string;
          status: string;
          processed_files: number;
          failed_files: number;
        }[];
      };
      finalStatusData = data as Record<string, unknown>;
      if (data.status !== lastStatus) {
        console.log(
          `[seed]   Job status: ${data.status}` +
            (data.total_groups != null
              ? ` (${data.completed_groups ?? 0}/${data.total_groups} groups, ` +
                `${data.processed_files ?? 0} processed, ${data.failed_files ?? 0} failed)`
              : ""),
        );
        lastStatus = data.status;
      }
      if (data.status === "failed") {
        throw new Error(
          `Import job failed (last status response: ${JSON.stringify(data)})`,
        );
      }
      return data.status === "completed";
    },
    120_000,
    1000,
  );
  console.log(
    `[seed] Job completed. Final status: ${JSON.stringify(finalStatusData)}`,
  );
  // Log per-group breakdown for debugging
  const groups =
    (finalStatusData.groups as
      | {
          group_id: number | null;
          group_name: string;
          status: string;
          processed_files: number;
          failed_files: number;
        }[]
      | undefined) ?? [];
  for (const g of groups) {
    console.log(
      `[seed]   Group "${g.group_name}": status=${g.status}, processed=${g.processed_files}, failed=${g.failed_files}`,
    );
  }

  // Import auto-finalizes when all groups complete — no manual finalize needed.
  console.log("[seed] Seed complete.");
}

/** Collect all supported media files recursively from a directory. */
function collectFiles(dir: string): string[] {
  const results: string[] = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      results.push(...collectFiles(full));
    } else if (/\.(jpe?g|png|webp|gif|mp4|webm)$/i.test(entry.name)) {
      results.push(full);
    }
  }
  return results;
}

/** Poll a condition function until it returns true or timeout. */
async function pollUntil(
  condition: () => Promise<boolean>,
  timeoutMs: number,
  intervalMs: number,
): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      if (await condition()) return;
    } catch (err) {
      throw err; // Propagate hard failures (e.g. job failed state)
    }
    await new Promise((r) => setTimeout(r, intervalMs));
  }
  throw new Error(`Polling timed out after ${timeoutMs}ms`);
}
