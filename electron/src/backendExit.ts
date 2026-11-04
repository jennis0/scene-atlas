/** Reading why the backend sidecar exited before it was ready. */

/** uvicorn's exit code when startup fails, binding the port included */
export const STARTUP_FAILURE = 3

// "[Errno 98] Address already in use" (Linux), "[Errno 48] ..." (macOS),
// "[Errno 10048] ... only one usage of each socket address ..." (Windows)
const PORT_TAKEN = /address already in use|errno 10048|only one usage of each socket address/i

/**
 * Whether the backend exited because its port was taken after Electron found it free:
 * another program (or another copy of Scene Atlas) bound it in between. Starting again
 * on another port then works.
 */
export function portWasTaken(code: number | null, lines: readonly string[]): boolean {
  return code === STARTUP_FAILURE && lines.some((line) => PORT_TAKEN.test(line))
}
