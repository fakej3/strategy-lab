import type { Config } from 'tailwindcss'

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // Deep blue-black backgrounds
        bg:      '#090C12',
        surface: '#0E1622',
        s2:      '#152030',
        s3:      '#1C2B3F',
        // Subtle blue-tinted borders
        border:  '#1D2D40',
        border2: '#253A52',
        border3: '#2D4765',
        // Amber accent — use sparingly, primary brand colour
        accent:      '#D4940C',
        'accent-dim': '#BA7F0A',
        'accent-bg':  '#D4940C0F',
        // Semantic — teal-green (profit) and coral red (loss)
        green:      '#34D399',
        'green-dim': '#10B981',
        red:        '#F87171',
        'red-dim':  '#EF4444',
        amber:      '#FBB030',
        // Text hierarchy — warm white, not cold blue
        text:   '#DDD9D0',
        muted:  '#6B7FA0',
        muted2: '#3D526A',
      },
      fontFamily: {
        mono: ['ui-monospace', '"JetBrains Mono"', '"Cascadia Code"', 'monospace'],
        ui:   ['system-ui', '"Inter"', '"Segoe UI"', 'sans-serif'],
      },
      fontSize: {
        '2xs': ['11px', '16px'],
        xs:    ['12px', '17px'],
        sm:    ['13px', '19px'],
        base:  ['14px', '21px'],
        md:    ['15px', '22px'],
        lg:    ['17px', '25px'],
        xl:    ['20px', '30px'],
        '2xl': ['24px', '32px'],
        '3xl': ['32px', '40px'],
        '4xl': ['42px', '50px'],
      },
      borderRadius: {
        sm: '3px',
        DEFAULT: '4px',
        md: '6px',
        lg: '8px',
        xl: '12px',
      },
      keyframes: {
        'fade-in': { from: { opacity: '0', transform: 'translateY(4px)' }, to: { opacity: '1', transform: 'translateY(0)' } },
      },
      animation: {
        'fade-in': 'fade-in 0.2s ease-out',
      },
    },
  },
  plugins: [],
} satisfies Config
