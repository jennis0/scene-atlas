import { ChildProcess, spawn } from 'child_process'
import * as net from 'net'
import * as path from 'path'
import { app } from 'electron'

/** Find a free TCP port by binding to port 0 and reading what the OS assigned. */
export function findFreePort(): Promise<number> {
  return new Promise((resolve, reject) => {
    const server = net.createServer()
    server.listen(0, '127.0.0.1', () => {
      const address = server.address()
      if (!address || typeof address === 'string') {
        reject(new Error('Could not determine free port'))
        return
      }
      const port = address.port
      server.close(() => resolve(port))
    })
    server.on('error', reject)
  })
}

/** Resolve the path to the sidecar executable. */
function getSidecarPath(): string {
  if (app.isPackaged) {
    const ext = process.platform === 'win32' ? '.exe' : ''
    return path.join(process.resourcesPath, 'sidecar', `scene-atlas-backend${ext}`)
  }
  // Dev: not used — backend runs manually
  return ''
}

export interface SidecarHandle {
  process: ChildProcess
  port: number
}

/**
 * Spawn the Python backend sidecar. Resolves once the backend emits the
 * SCENE_ATLAS_READY signal on stdout.
 */
export function spawnSidecar(
  port: number,
  appDataDir: string,
  imageLibraryDir: string,
  convertToWebp: boolean,
  onReady: (port: number) => void,
  onLog: (line: string) => void,
): ChildProcess {
  const sidecarPath = getSidecarPath()
  const child = spawn(
    sidecarPath,
    ['--port', String(port), '--app-data-dir', appDataDir, '--image-library-dir', imageLibraryDir],
    {
      stdio: ['ignore', 'pipe', 'pipe'],
      env: {
        ...process.env,
        CONVERT_TO_WEBP: convertToWebp ? '1' : '0',
      },
    },
  )

  let buffer = ''
  child.stdout?.on('data', (chunk: Buffer) => {
    buffer += chunk.toString()
    const lines = buffer.split('\n')
    buffer = lines.pop() ?? ''
    for (const line of lines) {
      onLog(`[backend] ${line}`)
      if (line.includes('SCENE_ATLAS_READY')) {
        onReady(port)
      }
    }
  })

  child.stderr?.on('data', (chunk: Buffer) => {
    for (const line of chunk.toString().split('\n')) {
      if (line.trim()) onLog(`[backend:err] ${line}`)
    }
  })

  child.on('error', (err) => {
    onLog(`[backend] Failed to start sidecar: ${err.message}`)
  })

  child.on('exit', (code, signal) => {
    onLog(`[backend] Sidecar exited (code=${code}, signal=${signal})`)
  })

  return child
}
