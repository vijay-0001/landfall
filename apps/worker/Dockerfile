FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY packages packages
COPY apps/api apps/api
COPY apps/worker apps/worker
COPY spikes/d6_tedb spikes/d6_tedb
RUN pip install -e packages/engine -e packages/register -e packages/classifier -e packages/paypal -e packages/rules -e packages/shipping -e apps/api -e apps/worker \
 && useradd --system --uid 10001 landfall && chown -R landfall /app
USER landfall
CMD ["python", "-m", "landfall_worker.main"]
