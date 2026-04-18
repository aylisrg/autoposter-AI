import { defineConfig } from "vite";
import { resolve } from "path";
import { copyFileSync, mkdirSync } from "fs";

export default defineConfig({
  build: {
    outDir: "dist",
    emptyOutDir: true,
    rollupOptions: {
      input: {
        background: resolve(__dirname, "src/background.ts"),
        "content/facebook": resolve(__dirname, "src/content/facebook.ts"),
      },
      output: {
        entryFileNames: "[name].js",
        format: "es",
      },
    },
  },
  plugins: [
    {
      name: "copy-manifest",
      writeBundle() {
        mkdirSync("dist", { recursive: true });
        copyFileSync("manifest.json", "dist/manifest.json");
        mkdirSync("dist/popup", { recursive: true });
        try {
          copyFileSync("src/popup/popup.html", "dist/popup/popup.html");
        } catch {
          /* popup is optional during dev */
        }
      },
    },
  ],
});
