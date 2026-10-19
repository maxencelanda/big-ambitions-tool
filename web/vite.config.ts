import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// En dev (npm run dev), l'API tourne via `python app.py` sur le port 8765.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": { target: "http://127.0.0.1:8765", changeOrigin: false } },
  },
});
