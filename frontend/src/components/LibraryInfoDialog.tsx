import { useState, useRef, useId } from 'react'
import { X, BookOpen, Settings2 } from 'lucide-react'
import { toast } from 'sonner'
import { Dialog, DialogContent } from '@/components/ui/dialog'
import { PanelTitle } from '@/components/ui/panel-title'
import { LibraryTab } from '@/components/settings/LibraryTab'
import {
  SettingsTabContent,
  type SettingsTabContentRef,
} from '@/components/settings/SettingsTabContent'

export interface LibraryInfoDialogProps {
  open: boolean
  onClose: () => void
}

type Tab = 'library' | 'settings'

const TABS = [
  { id: 'library' as const, label: 'Library', Icon: BookOpen },
  { id: 'settings' as const, label: 'Settings', Icon: Settings2 },
]

export function LibraryInfoDialog({ open, onClose }: LibraryInfoDialogProps) {
  const tabIdBase = useId()
  const [activeTab, setActiveTab] = useState<Tab>('library')
  const settingsRef = useRef<SettingsTabContentRef>(null)

  // Leaving the Settings tab (or the dialog) saves any unsaved changes.
  const saveSettingsIfDirty = async ({ notify }: { notify: boolean }) => {
    if (activeTab !== 'settings' || !settingsRef.current?.isDirty) return
    try {
      await settingsRef.current.save()
      if (notify) toast.success('Settings saved', { duration: 2000 })
    } catch (err) {
      if (notify) toast.error(err instanceof Error ? err.message : 'Failed to save settings')
      console.error('Save failed:', err)
    }
  }

  const handleTabChange = async (tab: Tab) => {
    if (tab === 'library') await saveSettingsIfDirty({ notify: true })
    setActiveTab(tab)
  }

  const handleOpenChange = async (v: boolean) => {
    if (v) return
    await saveSettingsIfDirty({ notify: false })
    onClose()
    // Wait out the close animation so the tab doesn't visibly switch.
    setTimeout(() => setActiveTab('library'), 200)
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="max-w-[480px] bg-card border-border/50 p-0 overflow-hidden">
        <div className="shrink-0 bg-popover">
          <div
            className="px-4 flex items-center justify-between"
            style={{ padding: '10px 12px 10px 16px' }}
          >
            <PanelTitle>{activeTab === 'library' ? 'Library' : 'Settings'}</PanelTitle>
            <button
              onClick={() => handleOpenChange(false)}
              className="h-7 w-7 rounded flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors"
            >
              <X className="h-3.5 w-3.5" />
              <span className="sr-only">Close</span>
            </button>
          </div>

          <SectionTabs idBase={tabIdBase} active={activeTab} onChange={handleTabChange} />
        </div>

        <div
          id={`${tabIdBase}-panel`}
          role="tabpanel"
          aria-labelledby={`${tabIdBase}-${activeTab}`}
          className="overflow-y-auto h-[380px]"
        >
          {/* Kept mounted while hidden, so a library purge keeps reporting progress */}
          <div hidden={activeTab !== 'library'}>
            <LibraryTab open={open} />
          </div>

          {activeTab === 'settings' && (
            <div className="px-5 pb-5 pt-4">
              <SettingsTabContent ref={settingsRef} dialogOpen={open} />
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}

/** Library | Settings, as tabs: arrow keys switch between them. */
function SectionTabs({
  idBase,
  active,
  onChange,
}: {
  idBase: string
  active: Tab
  onChange: (tab: Tab) => void
}) {
  return (
    <div
      role="tablist"
      aria-label="Sections"
      className="flex border-t border-border/50 px-5"
      onKeyDown={(e) => {
        if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return
        const next = active === 'library' ? 'settings' : 'library'
        onChange(next)
        document.getElementById(`${idBase}-${next}`)?.focus()
      }}
    >
      {TABS.map(({ id, label, Icon }) => (
        <button
          key={id}
          id={`${idBase}-${id}`}
          role="tab"
          aria-selected={active === id}
          aria-controls={`${idBase}-panel`}
          tabIndex={active === id ? 0 : -1}
          onClick={() => onChange(id)}
          className={`flex items-center gap-1.5 py-2.5 pr-5 text-[12px] font-medium border-b-2 -mb-px transition-colors duration-150 ${
            active === id
              ? 'border-primary text-foreground'
              : 'border-transparent text-muted-foreground hover:text-foreground'
          }`}
        >
          <Icon className="h-3.5 w-3.5" />
          {label}
        </button>
      ))}
    </div>
  )
}
