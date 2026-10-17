/** Whether an image has a detected square grid the overlay can draw. */
export function canShowGrid(image: {
  media_type?: string
  gridded: boolean | null
  grid_type: string | null
  grid_width: number | null
  grid_height: number | null
}): boolean {
  return (
    image.media_type !== 'video' &&
    image.gridded === true &&
    image.grid_type !== 'hex' &&
    !!image.grid_width &&
    !!image.grid_height
  )
}
