/** @type {import('tailwindcss').Config} */
export default {
  darkMode: ['class'],
  content: [
    './pages/**/*.{ts,tsx}',
    './components/**/*.{ts,tsx}',
    './app/**/*.{ts,tsx}',
    './src/**/*.{ts,tsx}',
  ],
  prefix: '',
  theme: {
    container: {
      center: true,
      padding: '2rem',
      screens: {
        '2xl': '1400px',
      },
    },
    extend: {
      // Below Tailwind's text-xs, for dense UI labels: 11px and 11.5px at the default text
      // size. Variables (index.css), because the larger text sizes raise them faster than
      // the rest of the scale. Font size only: line height is inherited.
      fontSize: {
        '3xs': 'var(--text-3xs)',
        '2xs': 'var(--text-2xs)',
      },
      fontFamily: {
        sans: ['"Figtree Variable"', 'system-ui', 'sans-serif'],
        // Titles and map names: a book serif with real lowercase, readable at any size
        display: ['"Newsreader Variable"', 'Georgia', 'serif'],
        // The "Scene Atlas" wordmark only
        wordmark: ['"Cinzel Variable"', 'Georgia', 'serif'],
        mono: ['"JetBrains Mono Variable"', 'Consolas', 'monospace'],
      },
      colors: {
        border: 'hsl(var(--border))',
        input: 'hsl(var(--input))',
        ring: 'hsl(var(--ring))',
        background: 'hsl(var(--background))',
        foreground: 'hsl(var(--foreground))',
        primary: {
          DEFAULT: 'hsl(var(--primary))',
          foreground: 'hsl(var(--primary-foreground))',
        },
        secondary: {
          DEFAULT: 'hsl(var(--secondary))',
          foreground: 'hsl(var(--secondary-foreground))',
        },
        success: 'hsl(var(--success))',
        warning: 'hsl(var(--warning))',
        destructive: {
          DEFAULT: 'hsl(var(--destructive))',
          foreground: 'hsl(var(--destructive-foreground))',
        },
        muted: {
          DEFAULT: 'hsl(var(--muted))',
          foreground: 'hsl(var(--muted-foreground))',
        },
        accent: {
          DEFAULT: 'hsl(var(--accent))',
          foreground: 'hsl(var(--accent-foreground))',
        },
        popover: {
          DEFAULT: 'hsl(var(--popover))',
          foreground: 'hsl(var(--popover-foreground))',
        },
        card: {
          DEFAULT: 'hsl(var(--card))',
          foreground: 'hsl(var(--card-foreground))',
        },
        'surface-canvas': 'hsl(var(--surface-canvas))',
        // Shadow colour: black, its opacity scaled per mode by --shadow-strength (index.css)
        shade: 'hsl(0 0% 0% / calc(<alpha-value> * var(--shadow-strength)))',
      },
      // Text (and icon) colours use the ink variants, tuned to stay readable as text, also
      // on their own tints; bg-/border- keep the fill colours. See the palette notes in
      // design/visual-language.md.
      textColor: {
        primary: {
          DEFAULT: 'hsl(var(--primary-ink))',
          foreground: 'hsl(var(--primary-foreground))',
        },
        destructive: {
          DEFAULT: 'hsl(var(--destructive-ink))',
          foreground: 'hsl(var(--destructive-foreground))',
        },
        success: 'hsl(var(--success-ink))',
        warning: 'hsl(var(--warning-ink))',
      },
      borderRadius: {
        lg: 'var(--radius)',
        md: 'calc(var(--radius) - 2px)',
        sm: 'calc(var(--radius) - 4px)',
      },
      keyframes: {
        'accordion-down': {
          from: { height: '0' },
          to: { height: 'var(--radix-accordion-content-height)' },
        },
        'accordion-up': {
          from: { height: 'var(--radix-accordion-content-height)' },
          to: { height: '0' },
        },
      },
      animation: {
        'accordion-down': 'accordion-down 0.2s ease-out',
        'accordion-up': 'accordion-up 0.2s ease-out',
      },
    },
  },
  // Tag chips' high-contrast classes are built at runtime (toHighContrast in
  // components/import/tagColors.ts), so Tailwind can't see them in the source. The hue
  // list must match TAG_HUES there (tagColors.test.ts checks it).
  safelist: [
    {
      pattern:
        /^(text-(red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose|slate|gray|zinc|neutral|stone)-(200|300|700|900|950)|border-(red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose|slate|gray|zinc|neutral|stone)-500)$/,
    },
  ],
  plugins: [
    require('tailwindcss-animate'),
    // short: windows with little height in lines of text (zoomed in, or large text); see
    // lib/compactLayout.ts
    ({ addVariant }) => addVariant('short', 'html[data-short] &'),
    // hc: high contrast (Appearance → Contrast); see lib/contrast.ts
    ({ addVariant }) => addVariant('hc', 'html[data-contrast="high"] &'),
  ],
}
