/**
 * The server id behind an editor key, or null for one created locally. The group editor
 * keys groups and files by their server id as a string; a group split off in the editor
 * has a uuid until it's saved.
 */
export function serverId(id: string): number | null {
  return /^\d+$/.test(id) ? Number(id) : null
}
