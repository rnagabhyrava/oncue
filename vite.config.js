import { defineConfig } from "vite";
export default defineConfig({
  root: "frontend",
  build: {
    outDir: "../oncue/static",
    emptyOutDir: true,
    cssCodeSplit: false,
    rollupOptions: {
      output: {
        entryFileNames: "app.js",
        assetFileNames: "app.[ext]",
        codeSplitting: false,
      },
    },
  },
});
