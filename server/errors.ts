export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

export function json(data: unknown, init?: ResponseInit): Response {
  return Response.json(data, init);
}

export function route(
  handler: (request: Bun.BunRequest<string>) => Response | Promise<Response>,
) {
  return async (request: Bun.BunRequest<string>) => {
    try {
      return await handler(request);
    } catch (error) {
      if (error instanceof ApiError) {
        return json({ error: error.message }, { status: error.status });
      }
      console.error(error);
      return json(
        { error: error instanceof Error ? error.message : "Unexpected server error" },
        { status: 500 },
      );
    }
  };
}
