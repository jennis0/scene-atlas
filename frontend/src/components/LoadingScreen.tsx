import { Compass } from 'lucide-react'
import { useEffect, useState } from 'react'
import { isApp } from '@/lib/appMode'

interface LoadingScreenProps {
  status?: string
  isError?: boolean
  errorDetail?: string
}

/**
 * Parse a raw backend error string into a user-friendly summary + detail.
 *
 * When the raw string contains a Python traceback, the last line is
 * extracted as the summary (it typically contains the exception message)
 * and the full traceback is preserved as detail. Otherwise the raw
 * string is returned as both summary and detail.
 */
function parseBackendError(raw: string): { summary: string; detail: string } {
  const tracebackMarker = 'Traceback (most recent call last)'
  if (raw.includes(tracebackMarker)) {
    const lines = raw.trimEnd().split('\n')
    // Walk backward to find the last non-empty line (the exception)
    let summary = raw
    for (let i = lines.length - 1; i >= 0; i--) {
      const line = lines[i].trim()
      if (line) {
        summary = line
        break
      }
    }
    return { summary, detail: raw }
  }
  return { summary: raw, detail: raw }
}

function AnimatedDots() {
  const [count, setCount] = useState(1)
  useEffect(() => {
    const id = setInterval(() => setCount((c) => (c % 3) + 1), 600)
    return () => clearInterval(id)
  }, [])
  // Fixed-width span so surrounding text doesn't shift
  return (
    <span className="inline-block w-5 text-left" aria-hidden>
      {'.'.repeat(count)}
    </span>
  )
}

export function LoadingScreen({
  status = 'Starting up',
  isError = false,
  errorDetail,
}: LoadingScreenProps) {
  const [showDetail, setShowDetail] = useState(false)

  const amber = (alpha: number) => `hsl(var(--primary) / ${alpha})`
  const red = (alpha: number) => `hsl(var(--destructive) / ${alpha})`
  const accent = isError ? red : amber

  return (
    <div
      className={`fixed inset-0 z-50 flex flex-col items-center justify-center bg-background ${isApp ? 'drag-region' : ''}`}
    >
      <div
        className="absolute inset-0 opacity-60"
        style={{
          backgroundImage: `radial-gradient(circle, ${amber(0.04)} 1px, transparent 1px)`,
          backgroundSize: '28px 28px',
        }}
      />

      <div
        className="absolute inset-0"
        style={{
          background: `radial-gradient(ellipse 50% 40% at 50% 48%, ${accent(0.06)} 0%, transparent 100%)`,
        }}
      />

      <div className="relative flex flex-col items-center gap-8">
        <div className="relative flex h-36 w-36 items-center justify-center">
          {/* Outermost sonar-ping ring — expands outward and fades */}
          {!isError && (
            <div
              className="absolute h-32 w-32 rounded-full border animate-ping"
              style={{
                borderColor: amber(0.12),
                animationDuration: '2.4s',
                animationTimingFunction: 'ease-out',
              }}
            />
          )}

          {/* Second ring — slow breathe */}
          {!isError && (
            <div
              className="absolute h-26 w-26 rounded-full border animate-pulse"
              style={{ borderColor: amber(0.15), animationDuration: '3s' }}
            />
          )}

          <div
            className="absolute h-20 w-20 rounded-full border"
            style={{ borderColor: accent(0.25) }}
          />

          {/* Counter-spinning dashed ring */}
          <div
            className={[
              'absolute h-14 w-14 rounded-full border border-dashed',
              isError
                ? 'border-destructive/10'
                : 'animate-[spin_12s_linear_infinite_reverse] border-primary/10',
            ].join(' ')}
          />

          <Compass
            className={[
              'relative h-8 w-8',
              isError ? 'text-destructive/60' : 'animate-[spin_8s_linear_infinite] text-primary/70',
            ].join(' ')}
            strokeWidth={1.2}
          />
        </div>

        <div className="flex flex-col items-center gap-2">
          <h1 className="font-display text-2xl tracking-[0.2em] text-foreground/90">Scene Atlas</h1>
          <div
            className="h-px w-24"
            style={{
              backgroundImage: `linear-gradient(90deg, transparent, ${accent(0.4)}, transparent)`,
            }}
          />
        </div>

        <div className="flex flex-col items-center gap-3">
          <p className="font-mono text-xs tracking-wider">
            {isError ? (
              <span style={{ color: red(0.9) }}>{status}</span>
            ) : (
              <span className="text-muted-foreground">
                {status}
                <AnimatedDots />
              </span>
            )}
          </p>

          {isError &&
            errorDetail &&
            (() => {
              const { summary, detail } = parseBackendError(errorDetail)
              const hasTraceback = detail !== summary
              return (
                <div
                  className={`flex flex-col items-center gap-2 max-w-sm ${isApp ? 'no-drag-region' : ''}`}
                >
                  {hasTraceback && (
                    <p
                      className="font-mono text-[11px] tracking-wider text-center"
                      style={{ color: red(0.85) }}
                    >
                      {summary}
                    </p>
                  )}
                  <button
                    onClick={() => setShowDetail((v) => !v)}
                    className="font-mono text-[10px] tracking-wider text-muted-foreground/50 hover:text-muted-foreground/80 transition-colors"
                  >
                    {showDetail ? '▲ hide details' : '▼ show details'}
                  </button>
                  {showDetail && (
                    <pre className="mt-1 max-h-40 w-full overflow-y-auto rounded border border-border/30 bg-muted/20 p-3 font-mono text-[10px] leading-relaxed text-muted-foreground/70 whitespace-pre-wrap break-all">
                      {detail}
                    </pre>
                  )}
                </div>
              )
            })()}

          {!isError && (
            <p className="font-mono text-[10px] tracking-wider text-muted-foreground/30">
              First launch may take a moment to set up
            </p>
          )}
        </div>
      </div>
    </div>
  )
}
