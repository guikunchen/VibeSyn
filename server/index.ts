import { basename, join, resolve } from "node:path";
import type {
  AgentConfig,
  EndpointConfig,
  EndpointKind,
} from "../shared/types.ts";
import {
  dispatchEndpointTask,
  listEndpoints,
  queryDeviceStatus,
  readEndpointConfig,
  readEndpointState,
  readRetroPath,
  submitEndpointFeedback,
  testHttpEndpoint,
  testMongoEndpoint,
  writeEndpointConfig,
} from "./endpoints.ts";
import { ApiError, json, route } from "./errors.ts";
import {
  ICONS_DIR,
  ROOT,
  buildAgentGraph,
  continueTask,
  createAgent,
  createTask,
  deleteAgent,
  deleteTask,
  deleteTaskMessage,
  editTaskMessage,
  exportConfigZip,
  exportTaskZip,
  importConfigZip,
  importTaskZip,
  initializeRuntimeDirectories,
  latestTaskName,
  listTasks,
  readAgents,
  readResource,
  setEnabledAgents,
  stopTask,
  submitHumanResponse,
  taskView,
  updateAgent,
} from "./storage.ts";

initializeRuntimeDirectories();

const WEB_DIST = join(ROOT, "dist");

async function webAsset(request: Request): Promise<Response> {
  const pathname = new URL(request.url).pathname;
  const path = resolve(WEB_DIST, `.${pathname}`);
  if (!path.startsWith(`${WEB_DIST}/`)) throw new ApiError(404, "Asset does not exist.");

  const file = Bun.file(path);
  if (pathname !== "/" && (await file.exists())) return new Response(file);

  const index = Bun.file(join(WEB_DIST, "index.html"));
  if (!(await index.exists())) {
    throw new ApiError(404, "Frontend is not built. Run 'bun run build'.");
  }
  return new Response(index);
}

async function objectBody<T>(request: Request): Promise<T> {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    throw new ApiError(400, "Request body must contain valid JSON.");
  }
  if (!body || typeof body !== "object" || Array.isArray(body)) {
    throw new ApiError(400, "Request body must be a JSON object.");
  }
  return body as T;
}

async function uploadedFile(request: Request): Promise<File> {
  const form = await request.formData();
  const file = form.get("file");
  if (!(file instanceof File)) throw new ApiError(400, "A file upload is required.");
  return file;
}

function zipResponse(bytes: Uint8Array, name: string): Response {
  return new Response(bytes, {
    headers: {
      "Content-Type": "application/zip",
      "Content-Disposition": `attachment; filename="${name}"`,
    },
  });
}

function endpointKind(value: string): EndpointKind {
  if (value !== "devices" && value !== "tools") {
    throw new ApiError(404, "Endpoint kind does not exist.");
  }
  return value;
}

const isDevelopment = Bun.env.NODE_ENV === "development";

const server = Bun.serve({
  port: Number(isDevelopment ? Bun.env.API_PORT ?? 9001 : Bun.env.PORT ?? 9000),
  development:
    isDevelopment
      ? {
          hmr: true,
          console: true,
        }
      : false,
  routes: {
    "/api/agents": {
      GET: route(async () => json(readAgents())),
      POST: route(async (request) => {
        const body = await objectBody<{ name: string; config: AgentConfig }>(request);
        if (!body.config) throw new ApiError(400, "Agent configuration is required.");
        return json(createAgent(body.name, body.config), { status: 201 });
      }),
    },
    "/api/agents/enabled": {
      GET: route(async () =>
        json(
          Object.fromEntries(
            Object.entries(readAgents()).filter(([, config]) => config.enabled),
          ),
        ),
      ),
      PUT: route(async (request) => {
        const body = await objectBody<{ names: string[] }>(request);
        if (!Array.isArray(body.names)) throw new ApiError(400, "names must be an array.");
        return json(setEnabledAgents(body.names));
      }),
    },
    "/api/agents/:name": {
      GET: route(async (request) => {
        const agent = readAgents()[request.params.name];
        if (!agent) throw new ApiError(404, `Agent '${request.params.name}' does not exist.`);
        return json(agent);
      }),
      PUT: route(async (request) => {
        const config = await objectBody<AgentConfig>(request);
        return json(updateAgent(request.params.name, config));
      }),
      DELETE: route(async (request) => json(deleteAgent(request.params.name))),
    },
    "/api/config/export": {
      GET: route(async () => zipResponse(exportConfigZip(), "config_export.zip")),
    },
    "/api/config/import": {
      POST: route(async (request) => {
        const file = await uploadedFile(request);
        return json(importConfigZip(new Uint8Array(await file.arrayBuffer())));
      }),
    },
    "/api/graph": {
      GET: route(async (request) => {
        const url = new URL(request.url);
        const highlighted = url.searchParams.get("highlighted") ?? undefined;
        return json(buildAgentGraph(highlighted));
      }),
    },
    "/api/tasks": {
      GET: route(async () => json(listTasks())),
      POST: route(async (request) => {
        const body = await objectBody<{ name: string; description: string }>(request);
        return json(createTask(body.name, body.description), { status: 201 });
      }),
    },
    "/api/tasks/latest": {
      GET: route(async () => {
        const name = latestTaskName();
        return json(name ? taskView(name) : null);
      }),
    },
    "/api/tasks/import": {
      POST: route(async (request) => {
        const file = await uploadedFile(request);
        return json(importTaskZip(new Uint8Array(await file.arrayBuffer())), { status: 201 });
      }),
    },
    "/api/tasks/:name": {
      GET: route(async (request) => json(taskView(request.params.name))),
      DELETE: route(async (request) => {
        deleteTask(request.params.name);
        return new Response(null, { status: 204 });
      }),
    },
    "/api/tasks/:name/export": {
      GET: route(async (request) =>
        zipResponse(exportTaskZip(request.params.name), `${request.params.name}.zip`),
      ),
    },
    "/api/tasks/:name/actions/:action": {
      POST: route(async (request) => {
        const { name, action } = request.params;
        if (action === "continue") return json(continueTask(name));
        if (action === "stop") return json(stopTask(name));
        if (action === "human") {
          const body = await objectBody<{ response: string }>(request);
          return json(submitHumanResponse(name, body.response));
        }
        throw new ApiError(404, `Task action '${action}' does not exist.`);
      }),
    },
    "/api/tasks/:name/messages/:rawIndex": {
      PATCH: route(async (request) => {
        const body = await objectBody<{ content: string }>(request);
        return json(
          editTaskMessage(request.params.name, Number(request.params.rawIndex), body.content),
        );
      }),
      DELETE: route(async (request) =>
        json(deleteTaskMessage(request.params.name, Number(request.params.rawIndex))),
      ),
    },
    "/api/endpoints/:kind": {
      GET: route(async (request) => json(listEndpoints(endpointKind(request.params.kind)))),
    },
    "/api/endpoints/:kind/:name": {
      GET: route(async (request) =>
        json(readEndpointState(endpointKind(request.params.kind), request.params.name)),
      ),
    },
    "/api/endpoints/:kind/:name/config": {
      GET: route(async (request) =>
        json(readEndpointConfig(endpointKind(request.params.kind), request.params.name)),
      ),
      PUT: route(async (request) => {
        const config = await objectBody<EndpointConfig>(request);
        return json(
          writeEndpointConfig(endpointKind(request.params.kind), request.params.name, config),
        );
      }),
    },
    "/api/endpoints/:kind/:name/dispatch": {
      POST: route(async (request) => {
        const body = await objectBody<{ input: string }>(request);
        return json(
          dispatchEndpointTask(
            endpointKind(request.params.kind),
            request.params.name,
            body.input,
          ),
        );
      }),
    },
    "/api/endpoints/:kind/:name/feedback": {
      POST: route(async (request) => {
        const body = await objectBody<{ feedback: string }>(request);
        return json(
          submitEndpointFeedback(
            endpointKind(request.params.kind),
            request.params.name,
            body.feedback,
          ),
        );
      }),
    },
    "/api/endpoints/:kind/:name/test-http": {
      POST: route(async (request) =>
        json(await testHttpEndpoint(endpointKind(request.params.kind), request.params.name)),
      ),
    },
    "/api/endpoints/devices/:name/test-mongo": {
      POST: route(async (request) => json(await testMongoEndpoint(request.params.name))),
    },
    "/api/endpoints/devices/:name/status": {
      GET: route(async (request) => {
        const taskId = new URL(request.url).searchParams.get("taskId") ?? "";
        return json(await queryDeviceStatus(request.params.name, taskId));
      }),
    },
    "/api/endpoints/tools/RetroDesTool/retro/:path": {
      GET: route(async (request) => json(readRetroPath(Number(request.params.path)))),
    },
    "/api/tasks/:name/retro/:execution/:path": {
      GET: route(async (request) =>
        json(readRetroPath(Number(request.params.path), request.params.name, request.params.execution)),
      ),
    },
    "/api/resources/:task": {
      GET: route(async (request) => {
        const path = new URL(request.url).searchParams.get("path") ?? "";
        const parts = path.split("/").filter(Boolean);
        return new Response(Bun.file(readResource(request.params.task, parts)));
      }),
    },
    "/assets/icons/:name": {
      GET: route(async (request) => {
        const name = basename(request.params.name);
        const path = join(ICONS_DIR, name);
        const file = Bun.file(path);
        if (!(await file.exists())) throw new ApiError(404, "Icon does not exist.");
        return new Response(file);
      }),
    },
    "/assets/home.png": new Response(
      Bun.file(join(ICONS_DIR, "src/chem_main/resource/agent_icons/home.png")),
    ),
    "/vendor/rdkit/RDKit_minimal.wasm": {
      GET: route(async () => {
        const path = join(ROOT, "node_modules/@rdkit/rdkit/dist/RDKit_minimal.wasm");
        const file = Bun.file(path);
        if (!(await file.exists())) throw new ApiError(404, "RDKit WASM is not installed.");
        return new Response(file);
      }),
    },
    "/*": route(webAsset),
  },
});

console.log(`VibeSyn is running at ${server.url}`);
