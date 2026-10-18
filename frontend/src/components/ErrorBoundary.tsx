import React from 'react'
import { WindowDragBar } from './WindowDragBar'

interface Props {
  children: React.ReactNode
}

interface State {
  hasError: boolean
  error: Error | null
}

/**
 * Catches unhandled render errors and shows a recovery UI instead of
 * a blank white screen.  Wrap top-level pages with this component.
 */
class ErrorBoundary extends React.Component<Props, State> {
  constructor(props: Props) {
    super(props)
    this.state = { hasError: false, error: null }
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error('Unhandled render error:', error, info.componentStack)
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="flex flex-col items-center justify-center min-h-screen gap-4 p-8 text-center">
          {/* The gallery header, with its drag strip, is gone with the crash */}
          <WindowDragBar />
          <h2 className="text-xl font-semibold text-destructive">Something went wrong</h2>
          <p className="text-muted-foreground text-sm max-w-md">
            {import.meta.env.DEV
              ? (this.state.error?.message ?? 'An unexpected error occurred.')
              : 'An unexpected error occurred. Please reload the page.'}
          </p>
          <button
            onClick={() => window.location.reload()}
            className="px-4 py-2 bg-primary text-primary-foreground rounded-md hover:bg-primary/90 text-sm font-medium"
          >
            Reload page
          </button>
        </div>
      )
    }

    return this.props.children
  }
}

export default ErrorBoundary
