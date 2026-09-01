# Build the client, then ship it with the API in one image.
FROM node:22-slim AS client
WORKDIR /app/client
COPY client/package*.json ./
RUN npm ci
COPY client/ ./
RUN npm run build

FROM node:22-slim AS runtime
ENV NODE_ENV=production
# better-sqlite3 falls back to compiling from source if no prebuilt binary matches.
RUN apt-get update && apt-get install -y --no-install-recommends python3 make g++ \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY server/package*.json ./server/
RUN npm --prefix server ci --omit=dev

COPY server/ ./server/
COPY --from=client /app/client/dist ./client/dist

# The database lives on a volume so it survives container replacement.
ENV DATA_DIR=/data
RUN mkdir -p /data
VOLUME ["/data"]

ENV PORT=4000
EXPOSE 4000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD node -e "fetch('http://127.0.0.1:'+(process.env.PORT||4000)+'/api/health').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"

CMD ["node", "server/src/index.js"]
