/**
 * What the upgrade test checks, and how a library snapshot taken before an update is
 * compared with one taken after it (design/testing.md#upgrade-test).
 *
 * Integrity checks (the library's contents and every file loading) must always pass.
 * Search checks compare the results of the same queries before and after; a release that
 * changes search on purpose accepts those changes with the Release workflow's
 * accept_search_changes input. Pure (no I/O), so it is unit tested with `node --test`.
 */

/** e2e/upgrade/queries.json */
export interface QueryConfig {
  /** Default tolerance for semantic and hybrid queries */
  semanticDefaults: { top: number; minShared: number };
  /** Descriptions, searched by meaning only (the `~` prefix) */
  semantic: SemanticQuery[];
  /** Searched the default way: words and meaning combined, so ranked with tolerance */
  hybrid: string[];
  /** Searched by words only (the `=` prefix): exact results */
  text: string[];
  /** How many of each to build from the library itself: these depend on its contents */
  derived: { authors: number; tags: number; groupNames: number };
}

export interface SemanticQuery {
  query: string;
  top?: number;
  minShared?: number;
}

export type QueryKind = "exact" | "semantic";

export interface QuerySpec {
  id: string;
  kind: QueryKind;
  endpoint: "images" | "groups";
  params: Record<string, string | string[]>;
  top?: number;
  minShared?: number;
}

export interface QueryResult {
  id: string;
  /** Image ids, or group ids for the groups endpoint, in result order */
  ids: number[];
  error?: string;
}

/** The fields of an image that an update must never change */
export interface ImageRecord {
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
  /** "category:value", sorted */
  tags: string[];
}

export interface GroupRecord {
  name: string;
  author: string | null;
  /** Sorted */
  imageIds: number[];
}

export interface Integrity {
  /** The totals the API reports, checked against the listings */
  imageCount: number;
  groupCount: number;
  images: Record<string, ImageRecord>;
  groups: Record<string, GroupRecord>;
  /** Images whose thumbnail or original didn't load */
  unreadable: { id: number; what: string }[];
}

export interface Snapshot {
  version: string;
  integrity: Integrity;
  results: QueryResult[];
}

export interface SearchChange {
  spec: QuerySpec;
  before: number[];
  after: number[];
  rule: string;
}

export interface Comparison {
  integrityProblems: string[];
  searchChanges: SearchChange[];
  queryCount: number;
}

const BROWSE = { sort_by: "name", sort_dir: "asc", limit: "2000" };
const GROUP_BROWSE = { sort_by: "name", sort_dir: "asc", limit: "500" };
const RANKED = { sort_by: "relevance", limit: "50" };
const GROUPS_RANKED = { sort_by: "relevance", limit: "50" };

function slug(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
}

/** The most common values first, ties by name, so the plan is the same on every run. */
function mostCommon(values: (string | null)[], n: number): string[] {
  const counts = new Map<string, number>();
  for (const value of values) if (value) counts.set(value, (counts.get(value) ?? 0) + 1);
  return [...counts.entries()]
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .slice(0, n)
    .map(([value]) => value);
}

/**
 * Every query to run, from the config plus values taken from the library as it was before
 * the update. The same plan is run after the update.
 */
export function planQueries(config: QueryConfig, before: Integrity): QuerySpec[] {
  const images = Object.values(before.images);
  const groups = Object.values(before.groups);
  const specs: QuerySpec[] = [
    { id: "browse:images", kind: "exact", endpoint: "images", params: BROWSE },
    { id: "browse:groups", kind: "exact", endpoint: "groups", params: GROUP_BROWSE },
    { id: "type:battlemap", kind: "exact", endpoint: "images", params: { ...BROWSE, image_types: ["battlemap"] } },
    { id: "type:scene", kind: "exact", endpoint: "images", params: { ...BROWSE, image_types: ["scene"] } },
    { id: "gridded:yes", kind: "exact", endpoint: "images", params: { ...BROWSE, gridded: "true" } },
    { id: "gridded:no", kind: "exact", endpoint: "images", params: { ...BROWSE, gridded: "false" } },
  ];

  for (const author of mostCommon(images.map((i) => i.author), config.derived.authors)) {
    specs.push({ id: `author:${slug(author)}`, kind: "exact", endpoint: "images", params: { ...BROWSE, authors: [author] } });
  }
  for (const tag of mostCommon(images.flatMap((i) => i.tags), config.derived.tags)) {
    specs.push({ id: `tag:${slug(tag)}`, kind: "exact", endpoint: "images", params: { ...BROWSE, tags: [tag] } });
  }

  const groupNames = groups.map((g) => g.name).sort().slice(0, config.derived.groupNames);
  const words = [...config.text, ...groupNames];
  for (const query of [...new Set(words)]) {
    const params = { ...RANKED, query, text_only: "true" };
    specs.push({ id: `text:${slug(query)}`, kind: "exact", endpoint: "images", params });
    specs.push({ id: `text-groups:${slug(query)}`, kind: "exact", endpoint: "groups", params: { ...GROUPS_RANKED, query, text_only: "true" } });
  }

  const { top, minShared } = config.semanticDefaults;
  for (const query of config.hybrid) {
    specs.push({ id: `hybrid:${slug(query)}`, kind: "semantic", endpoint: "images", params: { ...RANKED, query }, top, minShared });
    specs.push({ id: `hybrid-groups:${slug(query)}`, kind: "semantic", endpoint: "groups", params: { ...GROUPS_RANKED, query }, top, minShared });
  }
  for (const q of config.semantic) {
    specs.push({
      id: `semantic:${slug(q.query)}`,
      kind: "semantic",
      endpoint: "images",
      params: { ...RANKED, query: q.query, semantic_only: "true" },
      top: q.top ?? top,
      minShared: q.minShared ?? minShared,
    });
  }
  return specs;
}

const RECORD_FIELDS: (keyof ImageRecord)[] = [
  "name",
  "author",
  "group_id",
  "image_type",
  "media_type",
  "gridded",
  "grid_width",
  "grid_height",
  "grid_type",
  "grid_source",
  "storage_key",
  "thumbnail_key",
  "content_hash",
  "tags",
];

function show(value: unknown): string {
  return JSON.stringify(value);
}

function compareIntegrity(before: Integrity, after: Integrity): string[] {
  const problems: string[] = [];
  for (const { id, what } of before.unreadable) {
    problems.push(`before the update, image ${id}'s ${what} didn't load (test setup)`);
  }
  for (const { id, what } of after.unreadable) {
    problems.push(`image ${id}'s ${what} didn't load after the update`);
  }
  if (before.imageCount !== after.imageCount) {
    problems.push(`image count changed: ${before.imageCount} → ${after.imageCount}`);
  }
  if (before.groupCount !== after.groupCount) {
    problems.push(`group count changed: ${before.groupCount} → ${after.groupCount}`);
  }
  for (const [id, was] of Object.entries(before.images)) {
    const now = after.images[id];
    if (!now) {
      problems.push(`image ${id} (${was.name}) is gone`);
      continue;
    }
    for (const field of RECORD_FIELDS) {
      if (show(was[field]) !== show(now[field])) {
        problems.push(`image ${id} (${was.name}): ${field} ${show(was[field])} → ${show(now[field])}`);
      }
    }
  }
  for (const id of Object.keys(after.images)) {
    if (!before.images[id]) problems.push(`image ${id} (${after.images[id].name}) appeared`);
  }
  for (const [id, was] of Object.entries(before.groups)) {
    const now = after.groups[id];
    if (!now) problems.push(`group ${id} (${was.name}) is gone`);
    else if (show(was) !== show(now)) problems.push(`group ${id}: ${show(was)} → ${show(now)}`);
  }
  for (const id of Object.keys(after.groups)) {
    if (!before.groups[id]) problems.push(`group ${id} (${after.groups[id].name}) appeared`);
  }
  return problems;
}

/** Null when the results match the query's rule; otherwise the rule they broke. */
function brokenRule(spec: QuerySpec, before: number[], after: number[]): string | null {
  if (spec.kind === "exact") {
    return show(before) === show(after) ? null : "same results in the same order";
  }
  const top = spec.top ?? 5;
  const k = Math.min(top, before.length);
  const minShared = Math.min(spec.minShared ?? top, k);
  const rule = `same top result, ${minShared} of the top ${k} shared`;
  if (k === 0) return after.length === 0 ? null : rule;
  const shared = after.slice(0, k).filter((id) => before.slice(0, k).includes(id)).length;
  return before[0] === after[0] && shared >= minShared ? null : rule;
}

export function compareSnapshots(specs: QuerySpec[], before: Snapshot, after: Snapshot): Comparison {
  const integrityProblems = compareIntegrity(before.integrity, after.integrity);
  const searchChanges: SearchChange[] = [];
  const beforeById = new Map(before.results.map((r) => [r.id, r]));
  const afterById = new Map(after.results.map((r) => [r.id, r]));

  for (const spec of specs) {
    const was = beforeById.get(spec.id);
    const now = afterById.get(spec.id);
    // A query that fails is broken, not changed: that is never accepted.
    if (!was || was.error) {
      integrityProblems.push(`query ${spec.id} failed before the update: ${was?.error ?? "not run"}`);
      continue;
    }
    if (!now || now.error) {
      integrityProblems.push(`query ${spec.id} failed after the update: ${now?.error ?? "not run"}`);
      continue;
    }
    const rule = brokenRule(spec, was.ids, now.ids);
    if (rule) searchChanges.push({ spec, before: was.ids, after: now.ids, rule });
  }
  return { integrityProblems, searchChanges, queryCount: specs.length };
}

export interface ReportOptions {
  fromVersion: string;
  toVersion: string;
  acceptSearchChanges: boolean;
  reason?: string;
  /** For the report: image and group names by id */
  imageNames: Record<string, string | null>;
  groupNames: Record<string, string>;
}

/** Whether the comparison fails the release. */
export function failsRelease(comparison: Comparison, acceptSearchChanges: boolean): boolean {
  return (
    comparison.integrityProblems.length > 0 ||
    (comparison.searchChanges.length > 0 && !acceptSearchChanges)
  );
}

function label(id: number, spec: QuerySpec, options: ReportOptions): string {
  const names = spec.endpoint === "groups" ? options.groupNames : options.imageNames;
  return `${names[String(id)] ?? "?"} (#${id})`;
}

function cell(text: string): string {
  return text.replace(/\|/g, "\\|");
}

/** The comparison as Markdown, for the job summary and the uploaded report. */
export function renderReport(comparison: Comparison, options: ReportOptions): string {
  const { integrityProblems, searchChanges, queryCount } = comparison;
  const lines = [`## Upgrade test: ${options.fromVersion} → ${options.toVersion}`, ""];

  if (integrityProblems.length === 0) {
    lines.push("**Library:** every image, group, tag, edit and file came through the update.");
  } else {
    lines.push(`**Library: ${integrityProblems.length} problem(s).** These always fail the release.`, "");
    for (const problem of integrityProblems) lines.push(`- ${problem}`);
  }
  lines.push("");

  if (searchChanges.length === 0) {
    lines.push(`**Search:** all ${queryCount} queries returned the same results.`);
    return lines.join("\n") + "\n";
  }
  const verdict = options.acceptSearchChanges
    ? `accepted: ${options.reason ?? "(no reason given)"}`
    : "this fails the release unless accepted with accept_search_changes";
  lines.push(`**Search: ${searchChanges.length} of ${queryCount} queries changed** (${verdict}).`, "");
  lines.push("| Query | Rule | Before | After |", "|---|---|---|---|");
  for (const change of searchChanges) {
    const shown = (ids: number[]) =>
      ids.slice(0, 5).map((id) => label(id, change.spec, options)).join("<br>") || "(none)";
    lines.push(
      `| ${cell(change.spec.id)} | ${change.rule} | ${cell(shown(change.before))} | ${cell(shown(change.after))} |`,
    );
  }
  return lines.join("\n") + "\n";
}
