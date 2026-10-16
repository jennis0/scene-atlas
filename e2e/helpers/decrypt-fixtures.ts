import { execSync } from "child_process";
import fs from "fs";
import path from "path";

const E2E_DIR = path.resolve(__dirname, "..");
const ENC_FILE = path.resolve(E2E_DIR, "fixtures", "e2e-images.zip.enc");

/**
 * Resolved path to the test images directory. E2E_IMAGE_DIR overrides it, to
 * run against a local set of images instead of the encrypted fixtures.
 */
export const IMAGE_DIR = process.env.E2E_IMAGE_DIR
  ? path.resolve(process.env.E2E_IMAGE_DIR)
  : path.resolve(E2E_DIR, ".tmp-images");

/**
 * Decrypt and extract test images from the encrypted fixture zip.
 * Requires the E2E_IMAGE_KEY environment variable.
 * Skips if images are already extracted.
 */
export function ensureTestImages(): string {
  // Already extracted — skip
  if (fs.existsSync(IMAGE_DIR) && fs.readdirSync(IMAGE_DIR).length > 0) {
    console.log(`[fixtures] Test images already present at ${IMAGE_DIR}`);
    return IMAGE_DIR;
  }

  const key = process.env.E2E_IMAGE_KEY;
  if (!key) {
    throw new Error(
      "E2E_IMAGE_KEY environment variable is required to decrypt test images.\n" +
        "Set it to run E2E tests locally, or add it as a GitHub Actions secret for CI.",
    );
  }

  if (!fs.existsSync(ENC_FILE)) {
    throw new Error(
      `Encrypted fixture file not found at ${ENC_FILE}.\n` +
        "Make sure you have the e2e/fixtures/e2e-images.zip.enc file (tracked via Git LFS).",
    );
  }

  console.log("[fixtures] Decrypting test images...");
  fs.mkdirSync(IMAGE_DIR, { recursive: true });

  const tmpZip = path.resolve(E2E_DIR, ".tmp-e2e-images.zip");
  try {
    // Decrypt — use -pass env: to avoid shell injection
    execSync(
      `openssl enc -aes-256-cbc -d -pbkdf2 -in "${ENC_FILE}" -out "${tmpZip}" -pass env:E2E_IMAGE_KEY`,
      { stdio: "inherit" },
    );

    // Extract — use tar on Unix, PowerShell on Windows
    if (process.platform === "win32") {
      execSync(
        `powershell -Command "Expand-Archive -Path '${tmpZip}' -DestinationPath '${IMAGE_DIR}' -Force"`,
        { stdio: "inherit" },
      );
    } else {
      execSync(`unzip -o "${tmpZip}" -d "${IMAGE_DIR}"`, { stdio: "inherit" });
    }

    console.log(`[fixtures] Test images extracted to ${IMAGE_DIR}`);
  } finally {
    // Clean up temp zip
    if (fs.existsSync(tmpZip)) {
      fs.unlinkSync(tmpZip);
    }
  }

  return IMAGE_DIR;
}
