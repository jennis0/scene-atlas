import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { RestartBadge } from './RestartBadge'

describe('RestartBadge', () => {
  it('is only a note until the setting changes', () => {
    render(<RestartBadge pending={false} onRestart={vi.fn()} />)
    expect(screen.getByText('Applies after a restart')).toBeInTheDocument()
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })

  it('restarts when the changed setting can be applied here', async () => {
    const onRestart = vi.fn()
    render(<RestartBadge pending onRestart={onRestart} />)
    await userEvent.click(screen.getByRole('button', { name: 'Restart to apply' }))
    expect(onRestart).toHaveBeenCalledOnce()
  })

  it('says to restart the server where the app cannot restart itself', () => {
    render(<RestartBadge pending />)
    expect(screen.getByText('Restart the server to apply')).toBeInTheDocument()
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })

  it('is disabled while restarting or until the change can apply', () => {
    const { rerender } = render(<RestartBadge pending onRestart={vi.fn()} restarting />)
    expect(screen.getByRole('button', { name: 'Restarting…' })).toBeDisabled()
    rerender(<RestartBadge pending onRestart={vi.fn()} disabled />)
    expect(screen.getByRole('button', { name: 'Restart to apply' })).toBeDisabled()
  })
})
