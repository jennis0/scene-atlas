import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { GpuStatus } from './GpuStatus'
import { ModelRatings } from './ModelRatings'
import type { ModelInfo } from '@/lib/api/modelsApi'

const medium = {
  name: 'medium',
  label: 'Medium',
  speed: { cpu: 2, gpu: 5 },
  search_quality: 4,
} as ModelInfo

describe('ModelRatings', () => {
  it('rates speed for this computer: without a GPU', () => {
    render(<ModelRatings model={medium} hasGpu={false} />)
    expect(screen.getByRole('img', { name: 'Speed: 2 out of 5' })).toBeInTheDocument()
    expect(screen.getByRole('img', { name: 'Search: 4 out of 5' })).toBeInTheDocument()
  })

  it('and with one', () => {
    render(<ModelRatings model={medium} hasGpu />)
    expect(screen.getByRole('img', { name: 'Speed: 5 out of 5' })).toBeInTheDocument()
  })

  it('renders nothing for a backend without ratings', () => {
    const { container } = render(
      <ModelRatings model={{ name: 'small', label: 'Small' } as ModelInfo} hasGpu={false} />,
    )
    expect(container).toBeEmptyDOMElement()
  })
})

describe('GpuStatus', () => {
  it('names the GPU it found', () => {
    render(<GpuStatus hasGpu provider="CUDAExecutionProvider" />)
    expect(screen.getByText('GPU found: NVIDIA (CUDA).')).toBeInTheDocument()
  })

  it('points to Small when there is no GPU', () => {
    render(<GpuStatus hasGpu={false} provider={null} />)
    expect(screen.getByText('No compatible GPU found.')).toBeInTheDocument()
    expect(screen.getByText(/Small is quickest/)).toBeInTheDocument()
  })
})
