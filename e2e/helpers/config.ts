/** Shared E2E test configuration constants. */

// Off the dev ports (8000, 5173), so a run never reuses a developer's backend
// and writes test data into their library.
export const BACKEND_PORT = Number(process.env.E2E_BACKEND_PORT ?? 18000);
export const FRONTEND_PORT = Number(process.env.E2E_FRONTEND_PORT ?? 15173);
export const BACKEND_URL = `http://127.0.0.1:${BACKEND_PORT}`;
