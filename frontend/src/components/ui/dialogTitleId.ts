import { createContext } from 'react'

/**
 * The id a DialogContent labels itself with. Title components (DialogTitle, PanelTitle)
 * rendered inside it take this id, so every dialog is named by its visible title.
 */
export const DialogTitleIdContext = createContext<string | undefined>(undefined)
