import { describe, it, expect } from 'vitest'
import { useState } from 'react'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { SegmentedControl } from './SegmentedControl'
import { SettingRow } from './SettingRow'

const SIZES = [
  { value: 'small', label: 'Small', title: 'Small text' },
  { value: 'default', label: 'Default', title: 'Default text' },
  { value: 'large', label: 'Large', title: 'Large text' },
] as const

type Size = (typeof SIZES)[number]['value']

function Harness({ initial = 'default' as Size }) {
  const [value, setValue] = useState<Size>(initial)
  return (
    <>
      <button type="button">Before</button>
      <SettingRow label="Text size" description="Makes text bigger." stacked>
        <SegmentedControl label="Text size" options={SIZES} value={value} onChange={setValue} />
      </SettingRow>
      <button type="button">After</button>
    </>
  )
}

describe('SegmentedControl', () => {
  it('is a single tab stop, on the checked option', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    await user.click(screen.getByRole('button', { name: 'Before' }))
    await user.tab()
    expect(screen.getByRole('radio', { name: 'Default' })).toHaveFocus()
    await user.tab()
    expect(screen.getByRole('button', { name: 'After' })).toHaveFocus()
  })

  it('arrow keys move and select, wrapping; Home and End jump to the ends', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    screen.getByRole('radio', { name: 'Default' }).focus()

    await user.keyboard('{ArrowRight}')
    expect(screen.getByRole('radio', { name: 'Large' })).toHaveFocus()
    expect(screen.getByRole('radio', { name: 'Large' })).toBeChecked()

    await user.keyboard('{ArrowRight}')
    expect(screen.getByRole('radio', { name: 'Small' })).toBeChecked()

    await user.keyboard('{ArrowLeft}')
    expect(screen.getByRole('radio', { name: 'Large' })).toBeChecked()

    await user.keyboard('{Home}')
    expect(screen.getByRole('radio', { name: 'Small' })).toHaveFocus()
    await user.keyboard('{End}')
    expect(screen.getByRole('radio', { name: 'Large' })).toBeChecked()
  })

  it("is described by its setting row's description", () => {
    render(<Harness />)
    expect(screen.getByRole('radiogroup', { name: 'Text size' })).toHaveAccessibleDescription(
      'Makes text bigger.',
    )
  })

  it('has no description outside a described row', () => {
    render(<SegmentedControl label="Size" options={SIZES} value="small" onChange={() => {}} />)
    expect(screen.getByRole('radiogroup')).not.toHaveAttribute('aria-describedby')
  })
})
