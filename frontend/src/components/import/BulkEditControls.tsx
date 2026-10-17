import { useState } from 'react'
import { ChevronDown } from 'lucide-react'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { onInlineEditKey } from '@/lib/inlineEditKeys'
import type { TagData } from '@/types'
import { TagPicker } from './TagPicker'
import type { ParsedTagVocab } from './types'

interface BulkEditControlsProps {
  vocab: ParsedTagVocab[]
  /** Subgroup labels offered in the Sub menu */
  existingSubgroups: string[]
  onAddTag: (tag: TagData) => void
  onSetGrid: (gridded: boolean | null, gridType: string | null) => void
  onSetImageType: (v: 'battlemap' | 'scene') => void
  onSetSubgroup: (v: string) => void
}

/** Tag, Type, Grid and Sub: the bulk edits shared by the file toolbar and the bulk panel. */
export function BulkEditControls({
  vocab,
  existingSubgroups,
  onAddTag,
  onSetGrid,
  onSetImageType,
  onSetSubgroup,
}: BulkEditControlsProps) {
  return (
    <>
      {vocab.length > 0 && <TagPicker vocab={vocab} existingTags={[]} onAdd={onAddTag} />}
      <TypeMenu onSetImageType={onSetImageType} />
      <GridMenu onSetGrid={onSetGrid} />
      <SubgroupMenu existingSubgroups={existingSubgroups} onSetSubgroup={onSetSubgroup} />
    </>
  )
}

type TypeMenuProps = Pick<BulkEditControlsProps, 'onSetImageType'>

function TypeMenu({ onSetImageType }: TypeMenuProps) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button className="h-7 px-2 rounded text-xs text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors flex items-center gap-1">
          Type <ChevronDown className="h-3 w-3" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuItem onClick={() => onSetImageType('battlemap')}>Battlemap</DropdownMenuItem>
        <DropdownMenuItem onClick={() => onSetImageType('scene')}>Scene</DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

type GridMenuProps = Pick<BulkEditControlsProps, 'onSetGrid'>

function GridMenu({ onSetGrid }: GridMenuProps) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button className="h-7 px-2 rounded text-xs text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors flex items-center gap-1">
          Grid <ChevronDown className="h-3 w-3" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuItem onClick={() => onSetGrid(true, 'square')}>Square</DropdownMenuItem>
        <DropdownMenuItem onClick={() => onSetGrid(true, 'hex')}>Hex</DropdownMenuItem>
        <DropdownMenuItem onClick={() => onSetGrid(false, null)}>Gridless</DropdownMenuItem>
        <DropdownMenuItem onClick={() => onSetGrid(null, null)}>Unknown</DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

type SubgroupMenuProps = Pick<BulkEditControlsProps, 'existingSubgroups' | 'onSetSubgroup'>

/** Set a subgroup: pick an existing label or type a new one. */
function SubgroupMenu({ existingSubgroups, onSetSubgroup }: SubgroupMenuProps) {
  const [subgroupInput, setSubgroupInput] = useState('')
  const [subOpen, setSubOpen] = useState(false)

  const applySubgroup = (value: string) => {
    onSetSubgroup(value)
    setSubgroupInput('')
    setSubOpen(false)
  }

  return (
    <Popover open={subOpen} onOpenChange={setSubOpen}>
      <PopoverTrigger asChild>
        <button className="h-7 px-2 rounded text-xs text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors flex items-center gap-1">
          Sub <ChevronDown className="h-3 w-3" />
        </button>
      </PopoverTrigger>
      <PopoverContent
        align="end"
        className="w-52 p-0"
        onOpenAutoFocus={(e: Event) => {
          e.preventDefault()
        }}
      >
        {existingSubgroups.length > 0 && (
          <>
            <div className="px-3 pt-2.5 pb-1 text-xs font-semibold text-muted-foreground">
              Existing
            </div>
            {existingSubgroups.map((sv) => (
              <button
                key={sv}
                onClick={() => applySubgroup(sv)}
                className="w-full text-left px-3 py-1.5 text-sm text-foreground hover:bg-secondary capitalize transition-colors"
              >
                {sv}
              </button>
            ))}
            <div className="h-px bg-border/50 my-1" />
          </>
        )}
        <div className="p-2 flex gap-1.5">
          <input
            autoFocus={existingSubgroups.length === 0}
            value={subgroupInput}
            onChange={(e) => setSubgroupInput(e.target.value)}
            placeholder="New subgroup…"
            className="flex-1 min-w-0 h-7 px-2 text-sm bg-secondary border border-border rounded text-foreground placeholder:text-muted-foreground"
            onKeyDown={(e) => {
              e.stopPropagation()
              onInlineEditKey(e, {
                onEnter: () => {
                  if (subgroupInput.trim()) applySubgroup(subgroupInput.trim())
                },
                onEscape: () => setSubOpen(false),
              })
            }}
          />
          <button
            className="h-7 px-2.5 text-xs shrink-0 rounded border border-border bg-secondary text-muted-foreground hover:text-foreground transition-colors"
            onClick={() => {
              if (subgroupInput.trim()) applySubgroup(subgroupInput.trim())
            }}
          >
            Set
          </button>
        </div>
      </PopoverContent>
    </Popover>
  )
}
