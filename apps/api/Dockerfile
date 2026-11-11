FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY packages packages
COPY apps/api apps/api
COPY spikes/d6_tedb spikes/d6_tedb
# Editable installs keep the register fixtures and data files beside the code they belong to.
RUN pip install -e packages/engine -e packages/register -e packages/classifier -e packages/paypal -e packages/rules -e packages/shipping -e apps/api \
 && useradd --system --uid 10001 landfall && chown -R landfall /app
USER landfall
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --retries=10 CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/health')"
CMD ["uvicorn", "landfall_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
