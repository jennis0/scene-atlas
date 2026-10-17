/** Friendly names for the ONNX Runtime GPU providers the backend reports. */
export const GPU_PROVIDER_LABELS: Record<string, string> = {
  CUDAExecutionProvider: 'NVIDIA (CUDA)',
  DmlExecutionProvider: 'DirectML',
  CoreMLExecutionProvider: 'Apple (Core ML)',
}
