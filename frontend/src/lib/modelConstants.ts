export const HARDWARE_BADGE: Record<string, { label: string; className: string }> = {
  cpu: {
    label: 'CPU',
    className: 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300',
  },
  gpu: {
    label: 'GPU',
    className: 'bg-purple-100 text-purple-700 dark:bg-purple-900/40 dark:text-purple-300',
  },
  any: {
    label: 'Any',
    className: 'bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300',
  },
}
