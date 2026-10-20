/**
 * Building a library in a running app and reading it back through its API, for the
 * upgrade test (design/testing.md#upgrade-test). The comparison itself is in checks.ts.
 */
import { seedTestData } from "../helpers/seed";
import type {
  GroupRecord,
  ImageRecord,
  Integrity,
  QueryResult,
  QuerySpec,
  Snapshot,
} from "./checks";

const MODEL = "small";
const PAGE = 500;

async function call<T>(base: string, method: string, path: string, json?: unknown): Promise<T> {
  const res = await fetch(`${base}/api/v1${path}`, {
    method,
    headers: json === undefined ? undefined : { "Content-Type": "application/json" },
    body: json === undefined ? undefined : JSON.stringify(json),
  });
  if (!res.ok) throw new Error(`${method} ${path} failed: ${res.status} ${await res.text()}`);
  return (await res.json()) as T;
}

function query(params: Record<string, string | string[]>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    for (const v of Array.isArray(value) ? value : [value]) search.append(key, v);
  }
  return search.toString();
}

async function waitFor(description: string, check: () => Promise<boolean>, timeoutMs: number) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (await check()) return;
    await new Promise((r) => setTimeout(r, 1000));
  }
  throw new Error(`Timed out after ${timeoutMs} ms waiting for ${description}`);
}

/** Make the small model active (downloading it unless it was copied in) and wait for it. */
export async function activateSearchModel(base: string): Promise<void> {
  await call(base, "POST", "/models/active", { model_name: MODEL });
  await waitFor(
    "the search model to load",
    async () => {
      const { status } = await call<{ status: string }>(base, "GET", "/models/embedding-status");
      if (status === "error" || status === "missing") throw new Error(`Search model ${status}`);
      return status === "ready";
    },
    15 * 60_000,
  );
}

interface ApiImage {
  id: number;
  name: string | null;
  author: string | null;
  group_id: number | null;
  image_type: string | null;
  media_type: string | null;
  gridded: boolean | null;
  grid_width: number | null;
  grid_height: number | null;
  grid_type: string | null;
  grid_source: string | null;
  storage_key: string;
  thumbnail_key: string | null;
  content_hash: string | null;
  tags: { category: string; value: string }[];
}

interface ApiGroup {
  group_id: number;
  base_name: string;
  author: string | null;
  all_image_ids: number[] | null;
}

export interface Edits {
  renamed: { id: number; name: string };
  grid: { id: number; grid_width: number; grid_height: number };
  tagged: { id: number; tag: string };
}

/** Import the test images, finish setup, and make the kinds of edit users make. */
export async function buildLibrary(base: string, imageDir: string): Promise<Edits> {
  await call(base, "POST", "/models/setup-complete");
  await seedTestData(imageDir, base);

  const images = await listImages(base);
  if (images.length < 3) throw new Error(`Expected at least 3 test images, got ${images.length}`);
  const [first, second, third] = images;

  const renamed = { id: first.id, name: "Upgrade test rename" };
  await call(base, "PATCH", `/images/${renamed.id}`, { name: renamed.name });
  const grid = { id: second.id, grid_width: 23, grid_height: 17 };
  await call(base, "PATCH", `/images/${grid.id}`, {
    gridded: true,
    grid_type: "square",
    grid_width: grid.grid_width,
    grid_height: grid.grid_height,
  });
  const tagged = { id: third.id, tag: "upgrade-test:kept" };
  await call(base, "POST", `/tags/image/${tagged.id}`, { category: "upgrade-test", value: "kept" });
  return { renamed, grid, tagged };
}

/** Problems with the edits in a snapshot; empty when all three are there. */
export function missingEdits(edits: Edits, integrity: Integrity): string[] {
  const problems: string[] = [];
  const byId = (id: number) => integrity.images[String(id)];
  if (byId(edits.renamed.id)?.name !== edits.renamed.name) problems.push("the rename");
  const grid = byId(edits.grid.id);
  if (
    grid?.grid_width !== edits.grid.grid_width ||
    grid?.grid_height !== edits.grid.grid_height ||
    grid?.grid_source !== "user"
  ) {
    problems.push("the grid edit");
  }
  if (!byId(edits.tagged.id)?.tags.includes(edits.tagged.tag)) problems.push("the added tag");
  return problems;
}

async function listImages(base: string): Promise<ApiImage[]> {
  const images: ApiImage[] = [];
  for (let offset = 0; ; offset += PAGE) {
    const page = await call<{ total: number; images: ApiImage[] }>(
      base,
      "GET",
      `/search/?${query({ sort_by: "name", sort_dir: "asc", limit: String(PAGE), offset: String(offset) })}`,
    );
    images.push(...page.images);
    if (page.images.length === 0 || images.length >= page.total) return images;
  }
}

async function listGroups(base: string): Promise<{ total: number; groups: ApiGroup[] }> {
  const groups: ApiGroup[] = [];
  for (let offset = 0; ; offset += PAGE) {
    const page = await call<{ total_groups: number; groups: ApiGroup[] }>(
      base,
      "GET",
      `/search/groups?${query({ sort_by: "name", sort_dir: "asc", limit: String(PAGE), offset: String(offset), include_all_image_ids: "true" })}`,
    );
    groups.push(...page.groups);
    if (page.groups.length === 0 || groups.length >= page.total_groups) {
      return { total: page.total_groups, groups };
    }
  }
}

async function readable(base: string, path: string): Promise<boolean> {
  try {
    const res = await fetch(`${base}${path}`);
    return res.ok && (await res.arrayBuffer()).byteLength > 0;
  } catch {
    return false;
  }
}

function record(image: ApiImage): ImageRecord {
  return {
    name: image.name,
    author: image.author,
    group_id: image.group_id,
    image_type: image.image_type,
    media_type: image.media_type,
    gridded: image.gridded,
    grid_width: image.grid_width,
    grid_height: image.grid_height,
    grid_type: image.grid_type,
    grid_source: image.grid_source,
    storage_key: image.storage_key,
    thumbnail_key: image.thumbnail_key,
    content_hash: image.content_hash,
    tags: image.tags.map((t) => `${t.category}:${t.value}`).sort(),
  };
}

export async function readIntegrity(base: string): Promise<Integrity> {
  const facets = await call<{ total_images: number }>(base, "GET", "/search/facets");
  const images = await listImages(base);
  const { total, groups } = await listGroups(base);

  const unreadable: Integrity["unreadable"] = [];
  for (const image of images) {
    if (!(await readable(base, `/api/v1/images/${image.id}/thumbnail`))) {
      unreadable.push({ id: image.id, what: "thumbnail" });
    }
    if (!(await readable(base, `/api/v1/images/${image.id}/file`))) {
      unreadable.push({ id: image.id, what: "original" });
    }
  }

  const groupRecords: Record<string, GroupRecord> = {};
  for (const g of groups) {
    groupRecords[String(g.group_id)] = {
      name: g.base_name,
      author: g.author,
      imageIds: [...(g.all_image_ids ?? [])].sort((a, b) => a - b),
    };
  }
  return {
    imageCount: facets.total_images,
    groupCount: total,
    images: Object.fromEntries(images.map((i) => [String(i.id), record(i)])),
    groups: groupRecords,
    unreadable,
  };
}

async function runQuery(base: string, spec: QuerySpec): Promise<QueryResult> {
  const path = spec.endpoint === "groups" ? "/search/groups" : "/search/";
  try {
    if (spec.endpoint === "groups") {
      const res = await call<{ groups: ApiGroup[] }>(base, "GET", `${path}?${query(spec.params)}`);
      return { id: spec.id, ids: res.groups.map((g) => g.group_id) };
    }
    const res = await call<{ images: ApiImage[] }>(base, "GET", `${path}?${query(spec.params)}`);
    return { id: spec.id, ids: res.images.map((i) => i.id) };
  } catch (err) {
    return { id: spec.id, ids: [], error: err instanceof Error ? err.message : String(err) };
  }
}

export async function takeSnapshot(
  base: string,
  version: string,
  integrity: Integrity,
  specs: QuerySpec[],
): Promise<Snapshot> {
  const results: QueryResult[] = [];
  for (const spec of specs) results.push(await runQuery(base, spec));
  return { version, integrity, results };
}
