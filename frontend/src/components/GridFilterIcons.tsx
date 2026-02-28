/** Grid-type filter icons used in FilterMenuContent. */

function gridColor(active: boolean, excluded: boolean): string {
  if (active) return 'hsl(var(--primary))'
  if (excluded) return 'hsl(var(--destructive))'
  return 'currentColor'
}

export function SquareGridSVG({ active, excluded }: { active: boolean; excluded: boolean }) {
  const c = gridColor(active, excluded)
  const op = active ? 0.7 : 0.5
  return (
    <svg width="40" height="34" viewBox="0 0 52 44" fill="none" style={{ color: c }}>
      <rect
        x="2"
        y="2"
        width="48"
        height="40"
        rx="3"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeOpacity="0.5"
      />
      <line
        x1="2"
        y1="15.3"
        x2="50"
        y2="15.3"
        stroke="currentColor"
        strokeWidth="1"
        strokeOpacity={op}
      />
      <line
        x1="2"
        y1="28.6"
        x2="50"
        y2="28.6"
        stroke="currentColor"
        strokeWidth="1"
        strokeOpacity={op}
      />
      <line
        x1="14"
        y1="2"
        x2="14"
        y2="42"
        stroke="currentColor"
        strokeWidth="1"
        strokeOpacity={op}
      />
      <line
        x1="26"
        y1="2"
        x2="26"
        y2="42"
        stroke="currentColor"
        strokeWidth="1"
        strokeOpacity={op}
      />
      <line
        x1="38"
        y1="2"
        x2="38"
        y2="42"
        stroke="currentColor"
        strokeWidth="1"
        strokeOpacity={op}
      />
    </svg>
  )
}

export function HexGridSVG({ active, excluded }: { active: boolean; excluded: boolean }) {
  const c = gridColor(active, excluded)
  const op = active ? 0.8 : 0.55
  return (
    <svg width="40" height="34" viewBox="0 0 52 44" fill="none" style={{ color: c }}>
      <rect
        x="2"
        y="2"
        width="48"
        height="40"
        rx="3"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeOpacity="0.4"
      />
      <polygon
        points="16,8 22,8 25,13 22,18 16,18 13,13"
        stroke="currentColor"
        strokeWidth="1.2"
        fill="none"
        strokeOpacity={op}
      />
      <polygon
        points="25,13 31,13 34,18 31,23 25,23 22,18"
        stroke="currentColor"
        strokeWidth="1.2"
        fill="none"
        strokeOpacity={op}
      />
      <polygon
        points="16,18 22,18 25,23 22,28 16,28 13,23"
        stroke="currentColor"
        strokeWidth="1.2"
        fill="none"
        strokeOpacity={op}
      />
      <polygon
        points="25,23 31,23 34,28 31,33 25,33 22,28"
        stroke="currentColor"
        strokeWidth="1.2"
        fill="none"
        strokeOpacity={op}
      />
      <polygon
        points="34,18 40,18 43,23 40,28 34,28 31,23"
        stroke="currentColor"
        strokeWidth="1.2"
        fill="none"
        strokeOpacity={op}
      />
    </svg>
  )
}

export function GridlessSVG({ active, excluded }: { active: boolean; excluded: boolean }) {
  const c = gridColor(active, excluded)
  return (
    <svg width="40" height="34" viewBox="0 0 52 44" fill="none" style={{ color: c }}>
      <rect
        x="2"
        y="2"
        width="48"
        height="40"
        rx="3"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeOpacity="0.5"
      />
      <rect
        x="10"
        y="10"
        width="32"
        height="24"
        rx="2"
        stroke="currentColor"
        strokeWidth="1"
        strokeDasharray="3 2"
        strokeOpacity="0.5"
      />
    </svg>
  )
}

export function AnyGridSVG({ active, excluded }: { active: boolean; excluded: boolean }) {
  const c = gridColor(active, excluded)
  return (
    <svg width="40" height="34" viewBox="0 0 52 44" fill="none" style={{ color: c }}>
      <rect
        x="2"
        y="2"
        width="48"
        height="40"
        rx="3"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeOpacity="0.4"
      />
      <line
        x1="2"
        y1="22"
        x2="28"
        y2="22"
        stroke="currentColor"
        strokeWidth="1"
        strokeOpacity="0.5"
        strokeDasharray="2 2"
      />
      <line
        x1="14"
        y1="2"
        x2="14"
        y2="42"
        stroke="currentColor"
        strokeWidth="1"
        strokeOpacity="0.5"
        strokeDasharray="2 2"
      />
      <polygon
        points="31,12 36,10 41,13 41,19 36,22 31,19"
        stroke="currentColor"
        strokeWidth="1.2"
        fill="none"
        strokeOpacity="0.65"
      />
      <polygon
        points="31,22 36,22 39,27 36,32 31,32 28,27"
        stroke="currentColor"
        strokeWidth="1.2"
        fill="none"
        strokeOpacity="0.65"
      />
    </svg>
  )
}

export function UnknownGridSVG({ active, excluded }: { active: boolean; excluded: boolean }) {
  const c = gridColor(active, excluded)
  return (
    <svg width="40" height="34" viewBox="0 0 52 44" fill="none" style={{ color: c }}>
      <rect
        x="2"
        y="2"
        width="48"
        height="40"
        rx="3"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeOpacity="0.4"
        strokeDasharray="4 2"
      />
      <text
        x="26"
        y="26"
        textAnchor="middle"
        dominantBaseline="middle"
        fontSize="16"
        fill="currentColor"
        fillOpacity="0.55"
        fontFamily="sans-serif"
      >
        ?
      </text>
    </svg>
  )
}
