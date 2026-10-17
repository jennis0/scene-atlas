import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { DndContext, useDraggable, useSensor, useSensors } from '@dnd-kit/core'
import {
  EditableAwareKeyboardSensor,
  EditableAwarePointerSensor,
  isEditableTarget,
} from './sensors'

function Draggable() {
  const { attributes, listeners, setNodeRef } = useDraggable({ id: 'card' })
  return (
    <div ref={setNodeRef} {...listeners} {...attributes} data-testid="card">
      <input aria-label="Name" />
    </div>
  )
}

function Harness({ onDragStart }: { onDragStart: () => void }) {
  const sensors = useSensors(
    useSensor(EditableAwarePointerSensor),
    useSensor(EditableAwareKeyboardSensor),
  )
  return (
    <DndContext sensors={sensors} onDragStart={onDragStart}>
      <Draggable />
    </DndContext>
  )
}

describe('editable-aware dnd sensors', () => {
  it('does not start a keyboard drag when Space is pressed in an input', () => {
    const onDragStart = vi.fn()
    render(<Harness onDragStart={onDragStart} />)
    fireEvent.keyDown(screen.getByLabelText('Name'), { code: 'Space', key: ' ' })
    expect(onDragStart).not.toHaveBeenCalled()
  })

  it('still starts a keyboard drag when Space is pressed on the draggable itself', () => {
    const onDragStart = vi.fn()
    render(<Harness onDragStart={onDragStart} />)
    fireEvent.keyDown(screen.getByTestId('card'), { code: 'Space', key: ' ' })
    expect(onDragStart).toHaveBeenCalledTimes(1)
  })

  it('identifies editable targets', () => {
    const input = document.createElement('input')
    const textarea = document.createElement('textarea')
    const div = document.createElement('div')
    expect(isEditableTarget(input)).toBe(true)
    expect(isEditableTarget(textarea)).toBe(true)
    expect(isEditableTarget(div)).toBe(false)
    expect(isEditableTarget(null)).toBe(false)
  })
})
