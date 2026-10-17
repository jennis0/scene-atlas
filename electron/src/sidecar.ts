import { ChildProcess, spawn } from 'child_process'
import * as net from 'net'
import * as path from 'path'
import { Readable } from 'stream'
import { app } from 'electron'

/** Find a free TCP port by binding to port 0 and reading what the OS assigned. */
/** *preferred* if it is free, otherwise any free port. */
export async function findFreePort(preferred?: number): Promise<number> {
  if (preferred !== undefined) {
    try {
      return await listenOnce(preferred)
    } catch {
      // Taken: fall through to an OS-assigned port.
    }
  }
  return listenOnce(0)
}

function listenOnce(port: number): Promise<number> {
  return new Promise((resolve, reject) => {
    const server = net.createServer()
    server.listen(port, '127.0.0.1', () => {
      const address = server.address()
      if (!address || typeof address === 'string') {
        reject(new Error('Could not determine free port'))
        return
      }
      const assigned = address.port
      server.close(() => resolve(assigned))
    })
    server.on('error', reject)
  })
}

function getSidecarPath(): string {
  if (!app.isPackaged) {
    throw new Error(
      'The backend sidecar is only spawned in packaged builds; run the backend manually in dev',
    )
  }
  const ext = process.platform === 'win32' ? '.exe' : ''
  return path.join(process.resourcesPath, 'sidecar', `scene-atlas-backend${ext}`)
}

/** Call onLine for each non-blank line, buffering partial lines across chunks. */
function forEachLine(stream: Readable | null, onLine: (line: string) => void): void {
  if (!stream) return
  stream.setEncoding('utf8')
  let buffer = ''
  stream.on('data', (chunk: string) => {
    buffer += chunk
    const lines = buffer.split(/\r?\n/)
    buffer = lines.pop() ?? ''
    for (const line of lines) {
      if (line.trim()) onLine(line)
    }
  })
  stream.on('end', () => {
    if (buffer.trim()) onLine(buffer)
    buffer = ''
  })
}

export interface SidecarOptions {
  port: number
  appDataDir: string
  imageLibraryDir: string
  convertToWebp: boolean
  /** Called when the backend prints SCENE_ATLAS_READY on stdout. */
  onReady: (port: number) => void
  onLog: (line: string) => void
  /** Called if the process could not be spawned (e.g. executable missing). */
  onError: (message: string) => void
}

/** Spawn the backend sidecar; calls onReady(port) when it prints SCENE_ATLAS_READY. */
export function spawnSidecar(options: SidecarOptions): ChildProcess {
  const { port, appDataDir, imageLibraryDir, convertToWebp, onReady, onLog, onError } = options
  const child = spawn(
    getSidecarPath(),
    [
      '--port',
      String(port),
      '--app-data-dir',
      appDataDir,
      '--image-library-dir',
      imageLibraryDir,
      '--parent-pid',
      String(process.pid),
    ],
    {
      // stdin is a pipe we never write to: when this process exits, however it exits,
      // the OS closes it and the sidecar's watchdog shuts the backend down.
      stdio: ['pipe', 'pipe', 'pipe'],
      env: {
        ...process.env,
        CONVERT_TO_WEBP: convertToWebp ? '1' : '0',
      },
    },
  )

  // EPIPE if the sidecar has already exited when we close its stdin.
  child.stdin?.on('error', () => {})

  forEachLine(child.stdout, (line) => {
    onLog(`[backend] ${line}`)
    if (line.includes('SCENE_ATLAS_READY')) onReady(port)
  })
  forEachLine(child.stderr, (line) => onLog(`[backend:err] ${line}`))

  child.on('error', (err) => {
    onLog(`[backend] Failed to start sidecar: ${err.message}`)
    onError(err.message)
  })

  child.on('exit', (code, signal) => {
    onLog(`[backend] Sidecar exited (code=${code}, signal=${signal})`)
  })

  return child
}
