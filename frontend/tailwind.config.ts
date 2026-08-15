import type { Config } from 'tailwindcss'

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        bg:      '#080b10',
        surface: '#0d1117',
        s2:      '#111820',
        s3:      '#162030',
        border:  '#1c2b3a',
        border2: '#243447',
        border3: '#2e4460',
        accent:  '#06b6d4',
        'accent-dim': '#0891b2',
        green:   '#10b981',
        red:     '#f43f5e',
        amber:   '#f59e0b',
        text:    '#c9d1d9',
        muted:   '#6e8899',
        muted2:  '#4a6070',
      },
      fontFamily: {
        mono: ['"JetBrains Mono"', '"Fira Code"', 'monospace'],
        ui:   ['"Inter"', '"Segoe UI"', 'system-ui', 'sans-serif'],
      },
      borderRadius: {
        sm: '4px',
        DEFAULT: '6px',
        md: '8px',
        lg: '12px',
      },
    },
  },
  plugins: [],
} satisfies Config
