// Keep the existing application unchanged while serving its built index at '/'.
const app = Bun.spawn(["bun", "server/index.ts"], {
  env: { ...process.env, PORT: "9001" },
  stdout: "inherit",
  stderr: "inherit",
});

const server = Bun.serve({
  port: Number(process.env.PORT ?? 9000),
  async fetch(request) {
    const url = new URL(request.url);
    if (url.pathname === "/") return new Response(Bun.file("dist/index.html"));
    url.hostname = "127.0.0.1";
    url.port = "9001";
    return fetch(new Request(url, request));
  },
});

function shutdown() {
  server.stop(true);
  app.kill();
}
process.on("SIGTERM", shutdown);
process.on("SIGINT", shutdown);
const status = await app.exited;
server.stop(true);
process.exit(status);
