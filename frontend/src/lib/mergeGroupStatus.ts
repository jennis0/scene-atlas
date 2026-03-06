import type { EditableGroupState, ImportGroupStatus } from '@/types'

/** Find the matching backend group status for an editable group.
 *  Matches by group_job_id (robust) with fallback to group_name. */
export function findGroupStatus(
  group: EditableGroupState,
  backendGroups: ImportGroupStatus[],
): ImportGroupStatus | undefined {
  return (
    (group.group_job_id && backendGroups.find((s) => s.group_job_id === group.group_job_id)) ||
    backendGroups.find((s) => s.group_name === group.group_name)
  )
}
