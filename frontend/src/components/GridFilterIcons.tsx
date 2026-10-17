/** Grid-type filter icons used in FilterMenuContent. */
import type { ReactNode } from 'react'

interface GridIconProps {
  active: boolean
  excluded: boolean
}

function gridColor(active: boolean, excluded: boolean): string {
  if (active) return 'hsl(var(--primary))'
  if (excluded) return 'hsl(var(--destructive))'
  return 'currentColor'
}

/** Shared 52×44 frame; children inherit `stroke="currentColor"` and `fill="none"`. */
function GridIconFrame({
  active,
  excluded,
  frameOpacity,
  frameDash,
  children,
}: GridIconProps & { frameOpacity: number; frameDash?: string; children: ReactNode }) {
  return (
    <svg
      width="40"
      height="34"
      viewBox="0 0 52 44"
      fill="none"
      stroke="currentColor"
      style={{ color: gridColor(active, excluded) }}
    >
      <rect
        x="2"
        y="2"
        width="48"
        height="40"
        rx="3"
        strokeWidth="1.5"
        strokeOpacity={frameOpacity}
        strokeDasharray={frameDash}
      />
      {children}
    </svg>
  )
}

const SQUARE_LINES = [
  [2, 15.3, 50, 15.3],
  [2, 28.6, 50, 28.6],
  [14, 2, 14, 42],
  [26, 2, 26, 42],
  [38, 2, 38, 42],
]

const HEXAGONS = [
  '16,8 22,8 25,13 22,18 16,18 13,13',
  '25,13 31,13 34,18 31,23 25,23 22,18',
  '16,18 22,18 25,23 22,28 16,28 13,23',
  '25,23 31,23 34,28 31,33 25,33 22,28',
  '34,18 40,18 43,23 40,28 34,28 31,23',
]

export function SquareGridSVG({ active, excluded }: GridIconProps) {
  return (
    <GridIconFrame active={active} excluded={excluded} frameOpacity={0.5}>
      {SQUARE_LINES.map(([x1, y1, x2, y2]) => (
        <line
          key={`${x1},${y1}`}
          x1={x1}
          y1={y1}
          x2={x2}
          y2={y2}
          strokeWidth="1"
          strokeOpacity={active ? 0.7 : 0.5}
        />
      ))}
    </GridIconFrame>
  )
}

export function HexGridSVG({ active, excluded }: GridIconProps) {
  return (
    <GridIconFrame active={active} excluded={excluded} frameOpacity={0.4}>
      {HEXAGONS.map((points) => (
        <polygon
          key={points}
          points={points}
          strokeWidth="1.2"
          strokeOpacity={active ? 0.8 : 0.55}
        />
      ))}
    </GridIconFrame>
  )
}

export function GridlessSVG({ active, excluded }: GridIconProps) {
  return (
    <GridIconFrame active={active} excluded={excluded} frameOpacity={0.5}>
      <rect
        x="10"
        y="10"
        width="32"
        height="24"
        rx="2"
        strokeWidth="1"
        strokeDasharray="3 2"
        strokeOpacity="0.5"
      />
    </GridIconFrame>
  )
}

export function AnyGridSVG({ active, excluded }: GridIconProps) {
  return (
    <GridIconFrame active={active} excluded={excluded} frameOpacity={0.4}>
      <line
        x1="2"
        y1="22"
        x2="28"
        y2="22"
        strokeWidth="1"
        strokeOpacity="0.5"
        strokeDasharray="2 2"
      />
      <line
        x1="14"
        y1="2"
        x2="14"
        y2="42"
        strokeWidth="1"
        strokeOpacity="0.5"
        strokeDasharray="2 2"
      />
      <polygon
        points="31,12 36,10 41,13 41,19 36,22 31,19"
        strokeWidth="1.2"
        strokeOpacity="0.65"
      />
      <polygon
        points="31,22 36,22 39,27 36,32 31,32 28,27"
        strokeWidth="1.2"
        strokeOpacity="0.65"
      />
    </GridIconFrame>
  )
}

export function UnknownGridSVG({ active, excluded }: GridIconProps) {
  return (
    <GridIconFrame active={active} excluded={excluded} frameOpacity={0.4} frameDash="4 2">
      <text
        x="26"
        y="26"
        textAnchor="middle"
        dominantBaseline="middle"
        fontSize="16"
        fill="currentColor"
        fillOpacity="0.55"
        stroke="none"
        fontFamily="sans-serif"
      >
        ?
      </text>
    </GridIconFrame>
  )
}
