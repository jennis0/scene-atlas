import { Compass } from 'lucide-react'

interface LoadingScreenProps {
  status?: string
}

/**
 * Full-page splash screen shown while the backend sidecar starts up.
 * Matches the app's cartographic aesthetic — Cinzel headings, amber accents,
 * dot-grid background, with a slowly rotating compass as the loading indicator.
 */
export function LoadingScreen({ status = 'Starting backend...' }: LoadingScreenProps) {
  return (
    <div className="fixed inset-0 z-50 flex flex-col items-center justify-center bg-background">
      {/* Dot-grid background — matches body style */}
      <div
        className="absolute inset-0 opacity-60"
        style={{
          backgroundImage:
            'radial-gradient(circle, hsl(37 27% 89% / 0.04) 1px, transparent 1px)',
          backgroundSize: '28px 28px',
        }}
      />

      {/* Faint radial glow behind the content */}
      <div
        className="absolute inset-0"
        style={{
          background:
            'radial-gradient(ellipse 50% 40% at 50% 48%, hsl(38 60% 58% / 0.06) 0%, transparent 100%)',
        }}
      />

      {/* Content */}
      <div className="relative flex flex-col items-center gap-8">
        {/* Compass spinner */}
        <div className="relative flex items-center justify-center">
          {/* Outer ring — static */}
          <div
            className="absolute h-20 w-20 rounded-full border border-primary/20"
            style={{ boxShadow: '0 0 30px hsl(38 60% 58% / 0.08)' }}
          />
          {/* Inner ring — slow counter-rotation for depth */}
          <div className="absolute h-14 w-14 animate-[spin_12s_linear_infinite_reverse] rounded-full border border-dashed border-primary/10" />
          {/* Compass icon — slow rotation */}
          <Compass
            className="h-8 w-8 animate-[spin_8s_linear_infinite] text-primary/70"
            strokeWidth={1.2}
          />
        </div>

        {/* Title */}
        <div className="flex flex-col items-center gap-2">
          <h1 className="font-display text-2xl tracking-[0.2em] text-foreground/90">
            Scene Atlas
          </h1>
          <div className="h-px w-24 bg-gradient-to-r from-transparent via-primary/40 to-transparent" />
        </div>

        {/* Status text */}
        <p className="font-mono text-xs tracking-wider text-muted-foreground">
          {status}
        </p>
      </div>
    </div>
  )
}
