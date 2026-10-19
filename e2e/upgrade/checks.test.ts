// Unit tests for the upgrade test's checks: npm run test:electron (node --test).
import { describe, test } from "node:test";
import * as assert from "node:assert/strict";
import {
  cell,
  compareSnapshots,
  failsRelease,
  planQueries,
  renderReport,
  type ImageRecord,
  type Integrity,
  type QueryConfig,
  type QuerySpec,
  type Snapshot,
} from "./checks.ts";

const CONFIG: QueryConfig = {
  semanticDefaults: { top: 5, minShared: 4 },
  semantic: [{ query: "dark cave with water" }, { query: "ship at sea", top: 3, minShared: 2 }],
  hybrid: ["cave"],
  text: ["Hydra"],
  derived: { authors: 1, tags: 1, groupNames: 1 },
};

function image(overrides: Partial<ImageRecord> = {}): ImageRecord {
  return {
    name: "Cave",
    author: "Ann",
    group_id: 1,
    image_type: "battlemap",
    media_type: "image",
    gridded: true,
    grid_width: 20,
    grid_height: 15,
    grid_type: "square",
    grid_source: "detector",
    storage_key: "ab/cd/key",
    thumbnail_key: "ab/cd/thumb",
    content_hash: "hash",
    tags: ["biome:cave"],
    ...overrides,
  };
}

function integrity(overrides: Partial<Integrity> = {}): Integrity {
  return {
    imageCount: 2,
    groupCount: 1,
    images: {
      "1": image(),
      "2": image({ name: "Cave Lava", author: "Bob", tags: ["biome:cave", "light:lava"] }),
    },
    groups: { "1": { name: "Cave", author: "Ann", imageIds: [1, 2] } },
    unreadable: [],
    ...overrides,
  };
}

function snapshot(results: Record<string, number[]>, over: Partial<Snapshot> = {}): Snapshot {
  return {
    version: "0.1.0",
    integrity: integrity(),
    results: Object.entries(results).map(([id, ids]) => ({ id, ids })),
    ...over,
  };
}

function spec(id: string, kind: QuerySpec["kind"], extra: Partial<QuerySpec> = {}): QuerySpec {
  return { id, kind, endpoint: "images", params: {}, ...extra };
}

describe("planQueries", () => {
  const specs = planQueries(CONFIG, integrity());
  const ids = specs.map((s) => s.id);

  test("covers browsing, filters, text, hybrid and semantic queries", () => {
    for (const id of [
      "browse:images",
      "browse:groups",
      "type:battlemap",
      "gridded:yes",
      "author:ann",
      "tag:biome-cave",
      "text:hydra",
      "text-groups:hydra",
      "text:cave",
      "hybrid:cave",
      "hybrid-groups:cave",
      "semantic:dark-cave-with-water",
    ]) {
      assert.ok(ids.includes(id), id);
    }
  });

  test("takes the most common authors and tags from the library", () => {
    assert.ok(!ids.includes("author:bob"));
    const tag = specs.find((s) => s.id === "tag:biome-cave")!;
    assert.deepEqual(tag.params.tags, ["biome:cave"]);
  });

  test("text and filters are exact; hybrid and semantic are tolerant", () => {
    assert.equal(specs.find((s) => s.id === "text:hydra")!.kind, "exact");
    assert.equal(specs.find((s) => s.id === "author:ann")!.kind, "exact");
    const semantic = specs.find((s) => s.id === "semantic:ship-at-sea")!;
    assert.equal(semantic.kind, "semantic");
    assert.equal(semantic.params.semantic_only, "true");
    assert.deepEqual([semantic.top, semantic.minShared], [3, 2]);
    const hybrid = specs.find((s) => s.id === "hybrid:cave")!;
    assert.deepEqual([hybrid.top, hybrid.minShared], [5, 4]);
  });

  test("is the same for the same library", () => {
    assert.deepEqual(planQueries(CONFIG, integrity()), specs);
  });
});

describe("compareSnapshots: integrity", () => {
  const specs = [spec("browse:images", "exact")];

  test("passes when nothing changed", () => {
    const result = compareSnapshots(specs, snapshot({ "browse:images": [1, 2] }), snapshot({ "browse:images": [1, 2] }));
    assert.deepEqual(result.integrityProblems, []);
    assert.deepEqual(result.searchChanges, []);
  });

  test("reports lost images, changed fields, lost edits and unreadable files", () => {
    const after = integrity({
      imageCount: 1,
      images: { "1": image({ grid_width: 21, tags: [] }) },
      groups: { "1": { name: "Cave", author: "Ann", imageIds: [1] } },
      unreadable: [{ id: 1, what: "thumbnail" }],
    });
    const result = compareSnapshots(
      specs,
      snapshot({ "browse:images": [1, 2] }),
      snapshot({ "browse:images": [1] }, { integrity: after }),
    );
    assert.deepEqual(result.integrityProblems, [
      "image 1's thumbnail didn't load after the update",
      "image count changed: 2 → 1",
      "image 1 (Cave): grid_width 20 → 21",
      'image 1 (Cave): tags ["biome:cave"] → []',
      "image 2 (Cave Lava) is gone",
      'group 1: {"name":"Cave","author":"Ann","imageIds":[1,2]} → {"name":"Cave","author":"Ann","imageIds":[1]}',
    ]);
  });

  test("a query that errors is a library problem, not a search change", () => {
    const after = snapshot({});
    after.results = [{ id: "browse:images", ids: [], error: "503" }];
    const result = compareSnapshots(specs, snapshot({ "browse:images": [1, 2] }), after);
    assert.deepEqual(result.integrityProblems, ["query browse:images failed after the update: 503"]);
    assert.deepEqual(result.searchChanges, []);
  });
});

describe("compareSnapshots: search", () => {
  test("exact queries must match in order", () => {
    const specs = [spec("text:cave", "exact")];
    const result = compareSnapshots(specs, snapshot({ "text:cave": [1, 2] }), snapshot({ "text:cave": [2, 1] }));
    assert.equal(result.searchChanges.length, 1);
    assert.equal(result.searchChanges[0].rule, "same results in the same order");
  });

  test("semantic queries tolerate small reorderings below the top result", () => {
    const specs = [spec("semantic:x", "semantic", { top: 5, minShared: 4 })];
    const before = snapshot({ "semantic:x": [1, 2, 3, 4, 5, 6] });
    const swapped = snapshot({ "semantic:x": [1, 3, 2, 4, 6, 5] });
    assert.deepEqual(compareSnapshots(specs, before, swapped).searchChanges, []);
  });

  test("semantic queries fail when the top result changes", () => {
    const specs = [spec("semantic:x", "semantic", { top: 5, minShared: 4 })];
    const result = compareSnapshots(
      specs,
      snapshot({ "semantic:x": [1, 2, 3, 4, 5] }),
      snapshot({ "semantic:x": [2, 1, 3, 4, 5] }),
    );
    assert.equal(result.searchChanges[0].rule, "same top result, 4 of the top 5 shared");
  });

  test("semantic queries fail when too few of the top results are shared", () => {
    const specs = [spec("semantic:x", "semantic", { top: 5, minShared: 4 })];
    const result = compareSnapshots(
      specs,
      snapshot({ "semantic:x": [1, 2, 3, 4, 5] }),
      snapshot({ "semantic:x": [1, 2, 3, 8, 9] }),
    );
    assert.equal(result.searchChanges.length, 1);
  });

  test("a short result list is compared on what it has", () => {
    const specs = [spec("semantic:x", "semantic", { top: 5, minShared: 4 })];
    const before = snapshot({ "semantic:x": [1, 2] });
    assert.deepEqual(compareSnapshots(specs, before, snapshot({ "semantic:x": [1, 2] })).searchChanges, []);
    assert.equal(compareSnapshots(specs, before, snapshot({ "semantic:x": [1, 7] })).searchChanges[0].rule, "same top result, 2 of the top 2 shared");
    assert.deepEqual(compareSnapshots(specs, snapshot({ "semantic:x": [] }), snapshot({ "semantic:x": [] })).searchChanges, []);
  });
});

describe("failsRelease and renderReport", () => {
  const specs = [spec("text:cave", "exact")];
  const changed = compareSnapshots(specs, snapshot({ "text:cave": [1, 2] }), snapshot({ "text:cave": [2] }));
  const options = {
    fromVersion: "0.0.0",
    toVersion: "0.1.0",
    imageNames: { "1": "Cave", "2": "Cave Lava" },
    groupNames: { "1": "Cave" },
  };

  test("search changes fail the release unless accepted", () => {
    assert.equal(failsRelease(changed, false), true);
    assert.equal(failsRelease(changed, true), false);
  });

  test("library problems fail the release even when search changes are accepted", () => {
    const broken = { ...changed, integrityProblems: ["image 2 (Cave Lava) is gone"] };
    assert.equal(failsRelease(broken, true), true);
  });

  test("the report shows each changed query and the reason it was accepted", () => {
    const report = renderReport(changed, { ...options, acceptSearchChanges: true, reason: "New ranking" });
    assert.match(report, /## Upgrade test: 0\.0\.0 → 0\.1\.0/);
    assert.match(report, /every image, group, tag, edit and file came through/);
    assert.match(report, /1 of 1 queries changed\*\* \(accepted: New ranking\)/);
    assert.match(report, /\| text:cave \| same results in the same order \| Cave \(#1\)<br>Cave Lava \(#2\) \| Cave Lava \(#2\) \|/);
  });

  test("table cells escape backslashes and pipes and stay on one line", () => {
    assert.equal(cell("a|b"), "a\\|b");
    assert.equal(cell("ends in \\"), "ends in \\\\");
    assert.equal(cell("a\\|b"), "a\\\\\\|b");
    assert.equal(cell("two\nlines"), "two lines");
  });

  test("the report says when search is unchanged", () => {
    const same = compareSnapshots(specs, snapshot({ "text:cave": [1] }), snapshot({ "text:cave": [1] }));
    assert.match(renderReport(same, { ...options, acceptSearchChanges: false }), /all 1 queries returned the same results/);
  });
});
