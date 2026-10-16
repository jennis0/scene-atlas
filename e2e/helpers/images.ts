import crypto from "crypto";
import fs from "fs";
import os from "os";
import path from "path";
import zlib from "zlib";

const CRC_TABLE = Array.from({ length: 256 }, (_, n) => {
  let c = n;
  for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
  return c >>> 0;
});

function crc32(buf: Buffer): number {
  let c = 0xffffffff;
  for (const b of buf) c = CRC_TABLE[(c ^ b) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

function chunk(type: string, data: Buffer): Buffer {
  const len = Buffer.alloc(4);
  len.writeUInt32BE(data.length);
  const body = Buffer.concat([Buffer.from(type, "ascii"), data]);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(body));
  return Buffer.concat([len, body, crc]);
}

/**
 * A small RGB PNG: a gradient with random noise, so every call produces bytes
 * (and pixels) that are not already in the library.
 */
export function makePng(width = 256, height = 256): Buffer {
  const noise = crypto.randomBytes(width * height);
  const rows: Buffer[] = [];
  for (let y = 0; y < height; y++) {
    const row = Buffer.alloc(1 + width * 3); // filter byte 0 = none
    for (let x = 0; x < width; x++) {
      const n = noise[y * width + x] >> 2;
      row[1 + x * 3] = ((x * 255) / width + n) & 0xff;
      row[2 + x * 3] = ((y * 255) / height + n) & 0xff;
      row[3 + x * 3] = (96 + n) & 0xff;
    }
    rows.push(row);
  }
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(width, 0);
  ihdr.writeUInt32BE(height, 4);
  ihdr[8] = 8; // bit depth
  ihdr[9] = 2; // RGB
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk("IHDR", ihdr),
    chunk("IDAT", zlib.deflateSync(Buffer.concat(rows))),
    chunk("IEND", Buffer.alloc(0)),
  ]);
}

/** Write a unique PNG to a fresh temp dir and return its path. */
export function writeUniquePng(name: string): string {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "scene-atlas-e2e-"));
  const file = path.join(dir, name);
  fs.writeFileSync(file, makePng());
  return file;
}

/** All media files under `dir`, recursively, in a stable order. */
export function listMediaFiles(dir: string): string[] {
  return fs
    .readdirSync(dir, { withFileTypes: true, recursive: true })
    .filter((e) => e.isFile() && /\.(jpe?g|png|webp|mp4|webm)$/i.test(e.name))
    .map((e) => path.join(e.parentPath, e.name))
    .sort();
}
