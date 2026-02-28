import fs from 'fs'
import path from 'path'

const BACKEND_URL = 'http://localhost:8000'

interface ImportFileInfo {
  relative_path: string
  filename: string
  name: string | null
  image_type: string | null
  gridded: boolean | null
  subgroup: string | null
  content_hash: string | null
  detected_tags: { category: string; value: string }[]
}

interface ImportGroup {
  author: string | null
  group_name: string
  files: ImportFileInfo[]
}

interface UploadResponse {
  job_id: string
  total_files: number
  groups: ImportGroup[]
}

/**
 * Seed the backend with test images via the import API.
 * Uploads images, confirms all groups, and waits for processing to complete.
 */
export async function seedTestData(imageDir: string): Promise<void> {
  // 1. Init an import job
  const initRes = await fetch(`${BACKEND_URL}/api/v1/imports/init`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: '{}',
  })
  if (!initRes.ok) throw new Error(`Failed to init import: ${initRes.status}`)
  const { job_id: jobId } = (await initRes.json()) as { job_id: string }

  // 2. Collect all image files
  const files = collectFiles(imageDir)
  if (files.length === 0) throw new Error(`No images found in ${imageDir}`)

  // 3. Upload files via multipart form
  const form = new FormData()
  form.append('job_id', jobId)

  const relativePaths: string[] = []
  for (const filePath of files) {
    const relativePath = path.relative(imageDir, filePath).replace(/\\/g, '/')
    relativePaths.push(relativePath)
    const buffer = fs.readFileSync(filePath)
    const blob = new Blob([buffer], { type: 'image/jpeg' })
    form.append('files', blob, path.basename(filePath))
  }
  form.append('relative_paths', JSON.stringify(relativePaths))

  const uploadRes = await fetch(`${BACKEND_URL}/api/v1/imports/upload`, {
    method: 'POST',
    body: form,
  })
  if (!uploadRes.ok) {
    const body = await uploadRes.text()
    throw new Error(`Upload failed: ${uploadRes.status} ${body}`)
  }
  const uploadData = (await uploadRes.json()) as UploadResponse

  // 4. Build confirm-all payload from the upload analysis
  const confirmGroups = uploadData.groups.map((group) => ({
    author: group.author || 'TestArtist',
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
  }))

  const confirmRes = await fetch(
    `${BACKEND_URL}/api/v1/imports/${jobId}/confirm-all`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ groups: confirmGroups }),
    },
  )
  if (!confirmRes.ok) {
    const body = await confirmRes.text()
    throw new Error(`Confirm failed: ${confirmRes.status} ${body}`)
  }

  // 5. Poll until processing completes
  await pollUntil(
    async () => {
      const res = await fetch(`${BACKEND_URL}/api/v1/imports/${jobId}/status`)
      const data = (await res.json()) as { state: string }
      return data.state === 'done'
    },
    120_000,
    1000,
  )

  // 6. Finalize the import
  await fetch(`${BACKEND_URL}/api/v1/imports/${jobId}/finalize`, {
    method: 'POST',
  })
}

/** Collect all .jpg/.jpeg files recursively from a directory. */
function collectFiles(dir: string): string[] {
  const results: string[] = []
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name)
    if (entry.isDirectory()) {
      results.push(...collectFiles(full))
    } else if (/\.jpe?g$/i.test(entry.name)) {
      results.push(full)
    }
  }
  return results
}

/** Poll a condition function until it returns true or timeout. */
async function pollUntil(
  condition: () => Promise<boolean>,
  timeoutMs: number,
  intervalMs: number,
): Promise<void> {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    try {
      if (await condition()) return
    } catch {
      // Ignore errors during polling, keep trying
    }
    await new Promise((r) => setTimeout(r, intervalMs))
  }
  throw new Error(`Polling timed out after ${timeoutMs}ms`)
}
