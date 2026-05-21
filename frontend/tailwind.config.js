/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        bg:       "var(--bg)",
        card:     "var(--bg-card)",
        accent:   "var(--accent)",
        border:   "rgba(255,255,255,0.07)",
      },
      fontFamily: {
        sans: ["Geist", "system-ui", "sans-serif"],
        mono: ["Geist Mono", "monospace"],
      },
    }
  },
  plugins: []
};