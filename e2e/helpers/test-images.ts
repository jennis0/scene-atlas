import { execSync } from 'child_process'
import path from 'path'

const PROJECT_ROOT = path.resolve(__dirname, '..', '..')
const SEED_SCRIPT = path.resolve(PROJECT_ROOT, 'scripts', 'generate_e2e_images.py')

/**
 * Generate test images by invoking the Python script.
 * Returns the list of relative paths generated.
 */
export function generateTestImages(outputDir: string): string[] {
  execSync(`uv run python "${SEED_SCRIPT}" --output-dir "${outputDir}"`, {
    cwd: PROJECT_ROOT,
    stdio: 'inherit',
  })

  const result = execSync(
    `uv run python "${SEED_SCRIPT}" --output-dir "${outputDir}" --list`,
    { cwd: PROJECT_ROOT },
  )
  return JSON.parse(result.toString())
}
