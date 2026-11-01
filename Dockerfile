FROM oven/bun:1.3-alpine AS build
WORKDIR /app
COPY package.json ./
ARG NPM_REGISTRY=https://registry.npmjs.org
RUN bun install --registry "$NPM_REGISTRY" --network-concurrency 16
COPY tsconfig.json vite.config.ts ./
COPY web ./web
COPY shared ./shared
RUN bun run build

FROM oven/bun:1.3-alpine AS runtime
WORKDIR /app
ENV NODE_ENV=production PORT=9000
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/dist ./dist
COPY package.json ./
COPY server ./server
COPY docker-entrypoint.ts ./
COPY shared ./shared
COPY src/chem_main ./src/chem_main
COPY history_files ./history_files
EXPOSE 9000
CMD ["bun", "docker-entrypoint.ts"]
