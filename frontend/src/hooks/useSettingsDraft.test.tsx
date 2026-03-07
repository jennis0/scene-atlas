import { renderHook, act, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useSettingsDraft } from './useSettingsDraft'
import * as settingsApi from '@/lib/api/settingsApi'
import { ReactNode } from 'react'

// Mock the API
vi.mock('@/lib/api/settingsApi')

const mockSettingsApi = settingsApi as any

// Create a query client for tests
const createQueryClient = () =>
  new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  })

const createWrapper = () => {
  const queryClient = createQueryClient()
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  )
}

describe('useSettingsDraft', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('initializes with empty draft and disabled query when enabled=false', async () => {
    mockSettingsApi.settingsApi.get.mockResolvedValue({
      enable_image_grid_detection: true,
      max_import_file_size: 10485760,
      max_concurrent_prepare: 4,
    })

    const { result } = renderHook(() => useSettingsDraft({ enabled: false }), {
      wrapper: createWrapper(),
    })

    // Query should not have fired
    expect(mockSettingsApi.settingsApi.get).not.toHaveBeenCalled()
    expect(result.current.draft).toEqual({})
    expect(result.current.isDirty).toBe(false)
    expect(result.current.isLoading).toBe(false)
  })

  it('fetches settings when enabled=true', async () => {
    const mockSettings = {
      enable_image_grid_detection: true,
      max_import_file_size: 10485760,
      max_concurrent_prepare: 4,
    }
    mockSettingsApi.settingsApi.get.mockResolvedValue(mockSettings)

    const { result } = renderHook(() => useSettingsDraft({ enabled: true }), {
      wrapper: createWrapper(),
    })

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false)
    })

    expect(mockSettingsApi.settingsApi.get).toHaveBeenCalled()
    expect(result.current.settings).toEqual(mockSettings)
  })

  it('setField marks draft as dirty', async () => {
    mockSettingsApi.settingsApi.get.mockResolvedValue({
      max_import_file_size: 10485760,
    })

    const { result } = renderHook(() => useSettingsDraft({ enabled: true }), {
      wrapper: createWrapper(),
    })

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false)
    })

    expect(result.current.isDirty).toBe(false)

    act(() => {
      result.current.setField('max_import_file_size', 5242880)
    })

    expect(result.current.isDirty).toBe(true)
    expect(result.current.draft.max_import_file_size).toBe(5242880)
  })

  it('save calls patch API and clears draft', async () => {
    const mockSettings = { max_import_file_size: 10485760 }
    mockSettingsApi.settingsApi.get.mockResolvedValue(mockSettings)
    mockSettingsApi.settingsApi.patch.mockResolvedValue({
      ...mockSettings,
      max_import_file_size: 5242880,
    })

    const { result } = renderHook(() => useSettingsDraft({ enabled: true }), {
      wrapper: createWrapper(),
    })

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false)
    })

    act(() => {
      result.current.setField('max_import_file_size', 5242880)
    })

    expect(result.current.isDirty).toBe(true)

    await act(async () => {
      await result.current.save()
    })

    expect(mockSettingsApi.settingsApi.patch).toHaveBeenCalledWith({
      max_import_file_size: 5242880,
    })
    expect(result.current.isDirty).toBe(false)
    expect(result.current.draft).toEqual({})
  })

  it('discard clears draft without API call', async () => {
    mockSettingsApi.settingsApi.get.mockResolvedValue({
      max_import_file_size: 10485760,
    })

    const { result } = renderHook(() => useSettingsDraft({ enabled: true }), {
      wrapper: createWrapper(),
    })

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false)
    })

    act(() => {
      result.current.setField('max_import_file_size', 5242880)
    })

    expect(result.current.isDirty).toBe(true)

    act(() => {
      result.current.discard()
    })

    expect(result.current.isDirty).toBe(false)
    expect(result.current.draft).toEqual({})
    expect(mockSettingsApi.settingsApi.patch).not.toHaveBeenCalled()
  })

  it('returns error state when query fails', async () => {
    const mockError = new Error('Network error')
    mockSettingsApi.settingsApi.get.mockRejectedValue(mockError)

    const { result } = renderHook(() => useSettingsDraft({ enabled: true }), {
      wrapper: createWrapper(),
    })

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false)
    })

    expect(result.current.isError).toBe(true)
    expect(result.current.error).toBeTruthy()
  })

  it('returns isSaving false after mutation completes', async () => {
    mockSettingsApi.settingsApi.get.mockResolvedValue({
      max_import_file_size: 10485760,
    })
    mockSettingsApi.settingsApi.patch.mockResolvedValue({
      max_import_file_size: 5242880,
    })

    const { result } = renderHook(() => useSettingsDraft({ enabled: true }), {
      wrapper: createWrapper(),
    })

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false)
    })

    act(() => {
      result.current.setField('max_import_file_size', 5242880)
    })

    // Initially not saving
    expect(result.current.isSaving).toBe(false)

    await act(async () => {
      await result.current.save()
    })

    // After save completes, still not saving
    expect(result.current.isSaving).toBe(false)
  })
})
