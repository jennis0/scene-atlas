/** Friendly names for the ONNX Runtime GPU providers the backend reports. */
export const GPU_PROVIDER_LABELS: Record<string, string> = {
  CUDAExecutionProvider: 'NVIDIA (CUDA)',
  DmlExecutionProvider: 'DirectML',
  CoreMLExecutionProvider: 'Apple (Core ML)',
}

/** The published models (model cards, versions, licences). */
export const MODEL_COLLECTION_URL = 'https://huggingface.co/collections/jennis0/scene-atlas-models'
