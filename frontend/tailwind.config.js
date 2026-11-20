/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', 'Segoe UI', 'Roboto', 'sans-serif'],
      },
      colors: {
        brand: {
          50: '#eef4ff', 100: '#dbe6fe', 200: '#bfd3fe', 300: '#93b4fd', 400: '#6090fa',
          500: '#3b6cf6', 600: '#2550eb', 700: '#1d3fd8', 800: '#1e35af', 900: '#1e318a', 950: '#172054',
        },
      },
      boxShadow: {
        card: '0 1px 2px rgba(16,24,40,.04), 0 1px 3px rgba(16,24,40,.06)',
      },
      keyframes: {
        blink: { '0%, 80%, 100%': { opacity: '.25', transform: 'translateY(0)' }, '40%': { opacity: '1', transform: 'translateY(-2px)' } },
      },
      animation: { blink: 'blink 1.2s infinite ease-in-out' },
    },
  },
  plugins: [],
};
