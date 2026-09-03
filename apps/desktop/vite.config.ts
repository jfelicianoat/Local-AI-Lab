import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

import paquete from "./package.json";

export default defineConfig({
  plugins: [react()],
  clearScreen: false,
  server: { port: 1420, strictPort: true },
  envPrefix: ["VITE_", "TAURI_"],
  // La version se inyecta desde package.json para que la ventana pueda
  // ensenarla sin que nadie tenga que mantenerla en dos sitios.
  define: { __APP_VERSION__: JSON.stringify(paquete.version) },
  build: { target: "es2022", minify: "esbuild", sourcemap: true },
});
