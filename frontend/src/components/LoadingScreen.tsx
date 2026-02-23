import { Compass } from 'lucide-react'

interface LoadingScreenProps {
  status?: string
  isError?: boolean
}

export function LoadingScreen({ status = 'Starting backend...', isError = false }: LoadingScreenProps) {
  return (
    <div className="fixed inset-0 z-50 flex flex-col items-center justify-center bg-background">
      {/* Dot-grid background */}
      <div
        className="absolute inset-0 opacity-60"
        style={{
          backgroundImage:
            'radial-gradient(circle, hsl(37 27% 89% / 0.04) 1px, transparent 1px)',
          backgroundSize: '28px 28px',
        }}
      />

      {/* Radial glow — amber normally, red-tinted on error */}
      <div
        className="absolute inset-0"
        style={{
          background: isError
            ? 'radial-gradient(ellipse 50% 40% at 50% 48%, hsl(0 62% 57% / 0.06) 0%, transparent 100%)'
            : 'radial-gradient(ellipse 50% 40% at 50% 48%, hsl(38 60% 58% / 0.06) 0%, transparent 100%)',
        }}
      />

      {/* Content */}
      <div className="relative flex flex-col items-center gap-8">
        {/* Compass — spins when loading, static on error */}
        <div className="relative flex items-center justify-center">
          <div
            className="absolute h-20 w-20 rounded-full border"
            style={{ borderColor: isError ? 'hsl(0 62% 57% / 0.2)' : 'hsl(38 60% 58% / 0.2)' }}
          />
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
              'h-8 w-8',
              isError
                ? 'text-destructive/60'
                : 'animate-[spin_8s_linear_infinite] text-primary/70',
            ].join(' ')}
            strokeWidth={1.2}
          />
        </div>

        {/* Title */}
        <div className="flex flex-col items-center gap-2">
          <h1 className="font-display text-2xl tracking-[0.2em] text-foreground/90">
            Scene Atlas
          </h1>
          <div
            className="h-px w-24 bg-gradient-to-r from-transparent to-transparent"
            style={{
              backgroundImage: isError
                ? 'linear-gradient(90deg, transparent, hsl(0 62% 57% / 0.4), transparent)'
                : 'linear-gradient(90deg, transparent, hsl(38 60% 58% / 0.4), transparent)',
            }}
          />
        </div>

        {/* Status text */}
        <p
          className="font-mono text-xs tracking-wider"
          style={{ color: isError ? 'hsl(0 62% 57% / 0.8)' : undefined }}
        >
          {!isError && <span className="text-muted-foreground">{status}</span>}
          {isError && status}
        </p>
      </div>
    </div>
  )
}
