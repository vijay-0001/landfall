FROM node:24-bookworm-slim
WORKDIR /app
COPY apps/renderer/package.json apps/renderer/package-lock.json* ./
RUN npm install --omit=dev --no-audit --no-fund \
 && npx playwright install --with-deps chromium \
 && rm -rf /var/lib/apt/lists/*
COPY apps/renderer/server.mjs ./
ENV PORT=3300
EXPOSE 3300
HEALTHCHECK --interval=15s --timeout=5s --retries=10 CMD node -e "fetch('http://127.0.0.1:3300/health').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"
CMD ["node", "server.mjs"]
