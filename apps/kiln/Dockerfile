FROM node:24-bookworm-slim
WORKDIR /app
COPY apps/kiln/package.json apps/kiln/server.mjs apps/kiln/admin.mjs apps/kiln/catalogue.json ./
COPY apps/kiln/public ./public
ENV PORT=3400
# The mock back office (add products and photos) is ON only when KILN_ADMIN_PASSWORD (10+ characters) is set; it is one shared staff account with a signed 8-hour session. Its data folder (a volume) is writable for that.
RUN mkdir -p /app/data && chown node /app/data
EXPOSE 3400
HEALTHCHECK --interval=15s --timeout=5s --retries=10 CMD node -e "fetch('http://127.0.0.1:3400/health').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"
USER node
CMD ["node", "server.mjs"]
