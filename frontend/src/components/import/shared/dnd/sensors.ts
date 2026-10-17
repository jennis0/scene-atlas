import { KeyboardSensor, PointerSensor } from '@dnd-kit/core'

/**
 * True when the event started inside a text-editing control. Draggable
 * wrappers spread dnd-kit listeners on an ancestor of these controls, so
 * without this check Space (keyboard drag) or a text-selecting pointer drag
 * inside an input would start dragging the whole card.
 */
export function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  if (target.isContentEditable) return true
  return target.closest('input, textarea, select, [contenteditable="true"]') !== null
}

/** KeyboardSensor that ignores key presses originating in editable fields. */
export class EditableAwareKeyboardSensor extends KeyboardSensor {
  static activators: typeof KeyboardSensor.activators = KeyboardSensor.activators.map(
    (activator) => ({
      ...activator,
      handler: (event, ...rest) =>
        !isEditableTarget(event.nativeEvent.target) && activator.handler(event, ...rest),
    }),
  )
}

/** PointerSensor that ignores pointer-downs originating in editable fields. */
export class EditableAwarePointerSensor extends PointerSensor {
  static activators: typeof PointerSensor.activators = PointerSensor.activators.map(
    (activator) => ({
      ...activator,
      handler: (event, ...rest) =>
        !isEditableTarget(event.nativeEvent.target) && activator.handler(event, ...rest),
    }),
  )
}
