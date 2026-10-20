export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(0)} KB`
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`
  return `${(bytes / 1024 ** 3).toFixed(2)} GB`
}

export function filenameStem(filename: string): string {
  return filename.replace(/\.[^.]+$/, '')
}

/**
 * An image's full name: its group's name then its own, as the gallery tiles show them.
 * Import strips the group's name from its images' names ("Frozen Lake" / "Snowy"), so the
 * image name alone is often just the variant.
 */
export function fullImageName(image: { name: string; group_name: string | null }): string {
  const { name, group_name } = image
  if (!group_name || name.toLowerCase().includes(group_name.toLowerCase())) return name
  return `${group_name} ${name}`
}
