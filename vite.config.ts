import { defineConfig, loadEnv } from "vite";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const apiTarget = `http://localhost:${env.API_PORT ?? "9001"}`;

  return {
    root: "web",
    define: {
      global: "globalThis",
      "process.env": JSON.stringify({ NODE_ENV: mode }),
    },
    build: {
      outDir: "../dist",
      commonjsOptions: { transformMixedEsModules: true },
      emptyOutDir: true,
    },
    server: {
      port: Number(env.PORT ?? 9000),
      proxy: {
        "^/api(?:/|$)": apiTarget,
        "/assets/home.png": apiTarget,
        "/assets/icons": apiTarget,
        "/vendor": apiTarget,
      },
    },
  };
});
