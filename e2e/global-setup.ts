import { execSync } from 'child_process'
import fs from 'fs'
import path from 'path'

export default function globalSetup() {
  const projectRoot = path.resolve(__dirname, '..')
  const tmpDataDir = path.resolve(__dirname, '.tmp-data')
  const imageDir = path.resolve(__dirname, '.tmp-images')

  // Clean data directory for fresh state
  if (fs.existsSync(tmpDataDir)) {
    fs.rmSync(tmpDataDir, { recursive: true })
  }
  fs.mkdirSync(tmpDataDir, { recursive: true })

  // Generate test images
  if (fs.existsSync(imageDir)) {
    fs.rmSync(imageDir, { recursive: true })
  }

  execSync(
    `uv run python scripts/generate_e2e_images.py --output-dir "${imageDir}"`,
    { cwd: projectRoot, stdio: 'inherit' },
  )

  // Store paths for fixtures to use
  process.env.E2E_IMAGE_DIR = imageDir
  process.env.E2E_DATA_DIR = tmpDataDir
}
