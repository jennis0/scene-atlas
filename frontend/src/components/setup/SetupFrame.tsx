import { useEffect, useRef, type ReactNode } from 'react'
import { Check } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { STEP_LABELS, type StepId, type StepNav } from './steps'

interface SetupFrameProps {
  nav: StepNav
  title: string
  description: ReactNode
  children: ReactNode
  /** The step's forward action; defaults to nav.onNext. Continue, or Finish on the last step. */
  onPrimary?: () => void
  primaryLabel?: string
  busy?: boolean
  primaryDisabled?: boolean
  /** Shown as an alert above the footer */
  error?: ReactNode
  /** Extra footer actions, before the primary button (e.g. "Skip for now") */
  secondary?: ReactNode
}

/** Layout shared by every setup step: wordmark, progress, heading, body, footer. */
export function SetupFrame({
  nav,
  title,
  description,
  children,
  onPrimary,
  primaryLabel,
  busy = false,
  primaryDisabled = false,
  error,
  secondary,
}: SetupFrameProps) {
  const isLast = nav.index === nav.steps.length - 1
  const heading = useRef<HTMLHeadingElement>(null)

  // Each step starts at its heading, so screen readers announce where the user is
  useEffect(() => {
    heading.current?.focus()
  }, [nav.index])

  return (
    <div className="min-h-dvh bg-background text-foreground flex justify-center px-4 py-8 sm:py-12">
      <main className="w-full max-w-[44rem] flex flex-col gap-6">
        <header className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-3">
          <p className="font-wordmark text-2xl font-medium tracking-wide">Scene Atlas</p>
          {nav.steps.length > 1 && <StepList steps={nav.steps} current={nav.index} />}
        </header>

        <div className="space-y-2">
          <h1
            ref={heading}
            tabIndex={-1}
            className="font-display text-2xl font-semibold focus:outline-none"
          >
            {title}
          </h1>
          <div className="text-sm text-muted-foreground leading-relaxed max-w-prose">
            {description}
          </div>
        </div>

        <div className="space-y-4">{children}</div>

        {error && (
          <div
            role="alert"
            className="rounded-lg border border-destructive/40 bg-destructive/5 p-3 text-sm"
          >
            {error}
          </div>
        )}

        <footer className="flex flex-wrap items-center gap-3 border-t border-border/50 pt-4">
          {nav.onBack && (
            <Button variant="ghost" onClick={nav.onBack} disabled={busy}>
              Back
            </Button>
          )}
          <div className="ml-auto flex flex-wrap items-center gap-3">
            {secondary}
            <Button onClick={onPrimary ?? nav.onNext} disabled={busy || primaryDisabled}>
              {busy ? 'Working…' : (primaryLabel ?? (isLast ? 'Finish' : 'Continue'))}
            </Button>
          </div>
        </footer>
      </main>
    </div>
  )
}

function StepList({ steps, current }: { steps: readonly StepId[]; current: number }) {
  return (
    <ol aria-label="Setup steps" className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
      {steps.map((step, i) => {
        const done = i < current
        const active = i === current
        return (
          <li
            key={step}
            aria-current={active ? 'step' : undefined}
            className={`flex items-center gap-1.5 ${active ? 'text-foreground font-medium' : 'text-muted-foreground'}`}
          >
            <span
              aria-hidden="true"
              className={`flex h-4 w-4 items-center justify-center rounded-full text-3xs tabular-nums ${
                active
                  ? 'bg-primary text-primary-foreground'
                  : done
                    ? 'bg-primary/15 text-primary'
                    : 'border border-border'
              }`}
            >
              {done ? <Check className="h-2.5 w-2.5" /> : i + 1}
            </span>
            {STEP_LABELS[step]}
            {done && <span className="sr-only"> (done)</span>}
          </li>
        )
      })}
    </ol>
  )
}
