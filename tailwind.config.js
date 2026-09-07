/** @type {import('tailwindcss').Config} */
export default {
  content: [
    './frontend/index.html',
    './frontend/src/**/*.{js,ts,jsx,tsx}',
  ],
  theme: {
    extend: {
      colors: {
        bg: '#09090b',
        surface: '#111113',
        s2: '#15171a',
        s3: '#1b1f24',
        border: '#27272a',
        border2: '#3f3f46',
        text: '#f4f4f5',
        muted: '#a1a1aa',
        muted2: '#71717a',
        accent: '#D4940C',
        'accent-dim': '#B67E0A',
        green: '#22c55e',
        amber: '#f59e0b',
        red: '#ef4444',
      },
      fontFamily: {
        ui: ['Inter', 'system-ui', 'sans-serif'],
      },
    },
  },
  plugins: [],
}
