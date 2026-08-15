import type { Config } from 'tailwindcss'

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // Backgrounds — deep navy, not black
        bg:      '#0B0F19',
        surface: '#0F1524',
        s2:      '#141C2E',
        s3:      '#1A2438',
        // Borders — subtle blue-tinted
        border:  '#1E2D45',
        border2: '#263650',
        border3: '#2E405E',
        // Blue accent — interactive, links, active states
        accent:     '#4D82F5',
        'accent-dim': '#3A6ADE',
        'accent-bg':  '#4D82F514',
        // Semantic
        green:   '#22C55E',
        'green-dim': '#16A34A',
        red:     '#F43F5E',
        'red-dim': '#E11D48',
        amber:   '#F59E0B',
        // Text hierarchy
        text:    '#CDD5E0',
        muted:   '#6878A0',
        muted2:  '#48587A',
      },
      fontFamily: {
        mono: ['"JetBrains Mono"', '"Fira Code"', 'ui-monospace', 'monospace'],
        ui:   ['"Inter"', '"Segoe UI"', 'system-ui', 'sans-serif'],
      },
      fontSize: {
        '2xs': ['10px', '14px'],
        xs:    ['11px', '16px'],
        sm:    ['12px', '18px'],
        base:  ['13px', '20px'],
        md:    ['14px', '20px'],
        lg:    ['16px', '24px'],
        xl:    ['18px', '28px'],
      },
      borderRadius: {
        sm: '3px',
        DEFAULT: '5px',
        md: '7px',
        lg: '10px',
      },
    },
  },
  plugins: [],
} satisfies Config
