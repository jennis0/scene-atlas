/** Open an import review on its Skipped entry rather than on a group */
export const SKIPPED_START = 'skipped'

/** Where an import review opens: a gallery group, or the Skipped entry */
export type ReviewStart = number | typeof SKIPPED_START
