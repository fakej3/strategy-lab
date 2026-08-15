import type { Config } from 'tailwindcss'

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // Backgrounds — near-black charcoal
        bg:      '#080C12',
        surface: '#0C1018',
        s2:      '#111822',
        s3:      '#16202C',
        // Borders — subtle, not blue-tinted
        border:  '#1C2836',
        border2: '#243444',
        border3: '#2C4058',
        // Amber accent — Bloomberg-style, single accent only
        accent:      '#D4980A',
        'accent-dim': '#BB8308',
        'accent-bg':  '#D4980A12',
        // Semantic — P&L and directional signals only
        green:      '#22C55E',
        'green-dim': '#16A34A',
        red:        '#F43F5E',
        'red-dim':  '#E11D48',
        amber:      '#F59E0B',
        // Text hierarchy
        text:   '#C8D5E0',
        muted:  '#5C7090',
        muted2: '#3C5070',
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
        sm: '2px',
        DEFAULT: '3px',
        md: '4px',
        lg: '6px',
      },
    },
  },
  plugins: [],
} satisfies Config
