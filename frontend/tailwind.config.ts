import type { Config } from "tailwindcss";

export default {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        navy: { 950: "#0A1A3F", 900: "#0E2352", 800: "#16306B", 700: "#28427F", 500: "#5B6B8C", 400: "#8A97B3" },
        brand: { 50: "#EEF4FF", 100: "#DCE7FE", 200: "#B9CEFD", 500: "#2563EB", 600: "#1D4FD8", 700: "#1A43B4" },
        teal: { 500: "#00A8B5" },
        line: "#E5E9F2",
        canvas: "#F7F9FC",
      },
      fontFamily: { sans: ["Inter", "ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "sans-serif"] },
      boxShadow: { card: "0 1px 2px rgba(10,26,63,0.04), 0 1px 3px rgba(10,26,63,0.06)" },
      borderRadius: { xl: "0.875rem" },
      keyframes: { fade: { from: { opacity: "0", transform: "translateY(4px)" }, to: { opacity: "1", transform: "none" } } },
      animation: { fade: "fade .25s ease-out" },
    },
  },
  plugins: [],
} satisfies Config;
