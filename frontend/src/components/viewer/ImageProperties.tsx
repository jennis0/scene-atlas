import { useRef } from 'react'
import { X } from 'lucide-react'
import { SubgroupDropdown } from '@/components/SubgroupDropdown'
import { GridToggle } from '@/components/import/GridToggle'
import { GridSizeInput } from '@/components/import/GridSizeInput'
import type { imageApi } from '@/lib/api'
import type { Image } from '@/types'

export type ImagePatch = Parameters<typeof imageApi.patch>[1]

interface ImagePropertiesProps {
  image: Image
  existingSubgroups: string[]
  editingSubgroup: boolean
  onEditingSubgroupChange: (editing: boolean) => void
  onPatch: (patch: ImagePatch) => void
  patching: boolean
}

function PropertyRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-2 mb-2">
      <span className="section-label w-[72px] shrink-0">{label}</span>
      {children}
    </div>
  )
}

/** Subgroup, type and grid rows of the viewer sidebar. */
export function ImageProperties({
  image,
  existingSubgroups,
  editingSubgroup,
  onEditingSubgroupChange,
  onPatch,
  patching,
}: ImagePropertiesProps) {
  return (
    <>
      <SubgroupRow
        image={image}
        existingSubgroups={existingSubgroups}
        editing={editingSubgroup}
        onEditingChange={onEditingSubgroupChange}
        onPatch={onPatch}
      />
      <TypeRow image={image} onPatch={onPatch} patching={patching} />
      {/* Scenes have no grid */}
      {image.image_type !== 'scene' && (
        <GridRow image={image} onPatch={onPatch} patching={patching} />
      )}
    </>
  )
}

interface SubgroupRowProps {
  image: Image
  existingSubgroups: string[]
  editing: boolean
  onEditingChange: (editing: boolean) => void
  onPatch: (patch: ImagePatch) => void
}

function SubgroupRow({
  image,
  existingSubgroups,
  editing,
  onEditingChange,
  onPatch,
}: SubgroupRowProps) {
  const triggerRef = useRef<HTMLButtonElement>(null)

  return (
    <div className="group/sv relative flex items-center gap-2 mb-2 min-w-0">
      <span className="section-label w-[72px] shrink-0">Subgroup</span>
      <div className="relative flex-1 min-w-0">
        <button
          ref={triggerRef}
          onClick={() => !editing && onEditingChange(true)}
          className={`w-full h-6 px-2 text-left text-xs bg-secondary border border-border flex items-center hover:border-primary/40 transition-colors ${editing ? 'rounded-t border-b-0' : 'rounded'}`}
          title={image.subgroup ?? undefined}
        >
          {image.subgroup ? (
            <span className="text-foreground/80 capitalize truncate pr-3">{image.subgroup}</span>
          ) : (
            <span className="text-muted-foreground italic">—</span>
          )}
        </button>
        {image.subgroup && (
          <button
            onClick={() => onPatch({ subgroup: null })}
            className="target-24 absolute right-1 top-1/2 -translate-y-1/2 z-10 opacity-0 focus-visible:opacity-100 [@media(hover:none)]:opacity-100 group-hover/sv:opacity-40 hover:!opacity-100 transition-opacity text-muted-foreground"
            title="Clear subgroup"
          >
            <X className="h-3 w-3" />
          </button>
        )}
        <SubgroupDropdown
          isOpen={editing}
          existingSubgroups={existingSubgroups}
          initialValue={image.subgroup ?? ''}
          variant="attached"
          triggerRef={triggerRef}
          onCommit={(val) => {
            onPatch({ subgroup: val || null })
            onEditingChange(false)
          }}
          onCancel={() => onEditingChange(false)}
        />
      </div>
    </div>
  )
}

interface PatchRowProps {
  image: Image
  onPatch: (patch: ImagePatch) => void
  patching: boolean
}

function TypeRow({ image, onPatch, patching }: PatchRowProps) {
  const typeButton = (type: Image['image_type'], label: string) => {
    const active = type === 'scene' ? image.image_type === 'scene' : image.image_type !== 'scene'
    return (
      <button
        aria-pressed={active}
        onClick={() => onPatch({ image_type: type })}
        disabled={patching}
        className={`px-2 py-1 text-2xs rounded-sm transition-colors ${
          active
            ? 'bg-primary/10 text-primary font-medium'
            : 'text-muted-foreground hover:text-foreground'
        }`}
      >
        {label}
      </button>
    )
  }

  return (
    <PropertyRow label="Type">
      <div
        role="group"
        aria-label="Type"
        className="inline-flex rounded border border-border p-px bg-secondary/50"
      >
        {typeButton('battlemap', 'Map')}
        {typeButton('scene', 'Scene')}
      </div>
    </PropertyRow>
  )
}

function GridRow({ image, onPatch, patching }: PatchRowProps) {
  return (
    <PropertyRow label="Grid">
      <div className="flex items-center gap-2 flex-1 min-w-0">
        <GridToggle
          gridded={image.gridded ?? null}
          gridType={image.grid_type ?? null}
          onChange={(gridded, gridType) => onPatch({ gridded, grid_type: gridType })}
          disabled={patching}
        />
        {image.gridded === true && (
          <GridSizeInput
            width={image.grid_width ?? null}
            height={image.grid_height ?? null}
            onChange={(w, h) => onPatch({ grid_width: w, grid_height: h })}
            disabled={patching}
          />
        )}
      </div>
    </PropertyRow>
  )
}
