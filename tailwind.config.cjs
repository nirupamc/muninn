/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./frontend/index.html",
    "./frontend/src/**/*.{ts,tsx}",
    "./node_modules/@mdrbx/nerv-ui/dist/**/*.{js,mjs}",
  ],
  theme: {
    extend: {
      colors: {
        "munin-bg": "#000000",
        "munin-panel": "#060806",
        "munin-panel-2": "#0b0e0b",
        "munin-border": "#1c241c",
        "munin-border-bright": "#2f3d2f",
        "munin-text": "#c8d6c8",
        "munin-muted": "#5d6b5d",
        "munin-green": "#27e36b",
        "munin-cyan": "#22d3ee",
        "munin-orange": "#ff9d2e",
        "munin-red": "#ff3b3b",
        "munin-purple": "#a472ff",
        "munin-amber": "#ffc24b",
        "status-active": "#27e36b",
        "status-superseded": "#ff9d2e",
        "status-conflict": "#ff3b3b",
        "status-consolidated": "#a472ff",
      },
      fontFamily: {
        display: ['"Oswald"', '"Arial Narrow"', "system-ui", "sans-serif"],
        mono: ['"JetBrains Mono"', '"Fira Code"', "ui-monospace", "Courier New", "monospace"],
        body: ['"Barlow Condensed"', '"Arial Narrow"', "system-ui", "sans-serif"],
      },
      boxShadow: {
        "munin-glow": "0 0 8px rgba(39,227,107,0.35)",
        "munin-glow-cyan": "0 0 8px rgba(34,211,238,0.35)",
      },
      keyframes: {
        "munin-flicker": {
          "0%, 100%": { opacity: "1" },
          "50%": { opacity: "0.86" },
          "54%": { opacity: "0.4" },
          "58%": { opacity: "0.95" },
          "60%": { opacity: "0.7" },
          "62%": { opacity: "1" },
        },
        "munin-blink": { "0%, 49%": { opacity: "1" }, "50%, 100%": { opacity: "0" } },
        "munin-sweep": { "0%": { transform: "translateX(-100%)" }, "100%": { transform: "translateX(100%)" } },
      },
      animation: {
        "munin-flicker": "munin-flicker 4s infinite",
        "munin-blink": "munin-blink 1s steps(1) infinite",
        "munin-sweep": "munin-sweep 2.4s linear infinite",
      },
    },
  },
  plugins: [],
};
