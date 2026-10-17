/** Recommended-hardware badges. Hues come from the tag palette (useHueColor), so they
 * get its light/dark and high-contrast variants and its contrast checks. */
export const HARDWARE_BADGE: Record<string, { label: string; hue: string }> = {
  cpu: { label: 'CPU', hue: 'blue' },
  gpu: { label: 'GPU', hue: 'purple' },
  any: { label: 'Any', hue: 'green' },
}
