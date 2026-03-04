import axios from 'axios'
import { getApiBaseUrl } from '../apiBase'

const api = axios.create({
  timeout: 30000,
  paramsSerializer: {
    indexes: null, // Format arrays as: ?tags=a&tags=b (no brackets)
  },
})

// Resolve base URL at request time (not import time) so the port injected
// by Electron's preload script is picked up after backend becomes ready.
api.interceptors.request.use((config) => {
  if (!config.baseURL) {
    config.baseURL = getApiBaseUrl()
  }
  return config
})

export { api }
