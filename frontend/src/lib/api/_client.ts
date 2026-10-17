import axios from 'axios'

// Same-origin in every mode: server mode, the Vite dev proxy, and Electron (the sidecar serves the UI).
const api = axios.create({
  baseURL: '/api/v1',
  timeout: 30000,
  paramsSerializer: {
    indexes: null, // Format arrays as: ?tags=a&tags=b (no brackets)
  },
})

export { api }
