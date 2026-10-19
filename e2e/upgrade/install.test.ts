// Unit tests for the upgrade test's update feed server: npm run test:electron (node --test).
import { after, before, describe, test } from "node:test";
import * as assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { parseRanges, serveFeed, type Feed } from "./install.ts";

describe("parseRanges", () => {
  test("reads single, open-ended, suffix and multiple ranges", () => {
    assert.deepEqual(parseRanges("bytes=0-9", 100), [{ start: 0, end: 9 }]);
    assert.deepEqual(parseRanges("bytes=90-", 100), [{ start: 90, end: 99 }]);
    assert.deepEqual(parseRanges("bytes=-10", 100), [{ start: 90, end: 99 }]);
    assert.deepEqual(parseRanges("bytes=0-1, 5-6", 100), [
      { start: 0, end: 1 },
      { start: 5, end: 6 },
    ]);
    assert.deepEqual(parseRanges("bytes=95-200", 100), [{ start: 95, end: 99 }]);
  });

  test("sends the whole file for no header or one it can't satisfy", () => {
    for (const header of [undefined, "items=0-1", "bytes=", "bytes=9-1", "bytes=100-", "bytes=a-b"]) {
      assert.equal(parseRanges(header, 100), null, String(header));
    }
  });
});

describe("serveFeed", () => {
  const content = Buffer.from(Array.from({ length: 256 }, (_, i) => i));
  let dir: string;
  let feed: Feed;

  before(async () => {
    dir = fs.mkdtempSync(path.join(os.tmpdir(), "feed-"));
    const served = path.join(dir, "feed");
    fs.mkdirSync(served);
    fs.writeFileSync(path.join(served, "Scene-Atlas-Setup-0.1.0.exe"), content);
    fs.writeFileSync(path.join(served, "latest.yml"), "version: 0.1.0\n");
    fs.writeFileSync(path.join(dir, "secret.txt"), "no");
    feed = await serveFeed(served);
  });

  after(async () => {
    await feed.close();
    fs.rmSync(dir, { recursive: true, force: true });
  });

  test("serves on the loopback address", () => {
    assert.match(feed.url, /^http:\/\/127\.0\.0\.1:\d+\/$/);
  });

  test("serves whole files and records what was asked for", async () => {
    const res = await fetch(`${feed.url}latest.yml`);
    assert.equal(res.status, 200);
    assert.equal(await res.text(), "version: 0.1.0\n");
    assert.ok(feed.requests.includes("latest.yml"));
  });

  test("serves one range", async () => {
    const res = await fetch(`${feed.url}Scene-Atlas-Setup-0.1.0.exe`, { headers: { Range: "bytes=10-19" } });
    assert.equal(res.status, 206);
    assert.equal(res.headers.get("content-range"), "bytes 10-19/256");
    assert.deepEqual(Buffer.from(await res.arrayBuffer()), content.subarray(10, 20));
  });

  test("serves several ranges as multipart/byteranges", async () => {
    const res = await fetch(`${feed.url}Scene-Atlas-Setup-0.1.0.exe`, {
      headers: { Range: "bytes=0-3,100-103" },
    });
    assert.equal(res.status, 206);
    assert.equal(res.headers.get("content-type"), "multipart/byteranges; boundary=scene-atlas-feed");
    const body = Buffer.from(await res.arrayBuffer());
    const part = (start: number, end: number) =>
      Buffer.concat([
        Buffer.from(
          `--scene-atlas-feed\r\nContent-Type: application/octet-stream\r\n` +
            `Content-Range: bytes ${start}-${end}/256\r\n\r\n`,
        ),
        content.subarray(start, end + 1),
        Buffer.from("\r\n"),
      ]);
    assert.deepEqual(body, Buffer.concat([part(0, 3), part(100, 103), Buffer.from("--scene-atlas-feed--\r\n")]));
  });

  test("404s for missing files and anything outside its folder", async () => {
    assert.equal((await fetch(`${feed.url}missing.yml`)).status, 404);
    assert.equal((await fetch(`${feed.url}..%2Fsecret.txt`)).status, 404);
  });
});
