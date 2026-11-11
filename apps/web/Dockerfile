FROM node:24-bookworm-slim AS build
WORKDIR /app
COPY apps/web/package.json apps/web/package-lock.json ./
COPY apps/web/stubs stubs
RUN npm ci --no-audit --no-fund
COPY apps/web/ ./
ARG NEXT_PUBLIC_SITE_URL=http://localhost
ARG API_PROXY_TARGET=
ENV NEXT_PUBLIC_SITE_URL=$NEXT_PUBLIC_SITE_URL NEXT_TELEMETRY_DISABLED=1 API_PROXY_TARGET=$API_PROXY_TARGET
RUN npm run build

FROM node:24-bookworm-slim
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
RUN useradd --system --uid 10001 landfall && chown -R landfall /app
USER landfall
EXPOSE 3000
HEALTHCHECK --interval=15s --timeout=5s --retries=10 CMD node -e "fetch('http://127.0.0.1:3000/').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"
CMD ["node", "server.js"]
