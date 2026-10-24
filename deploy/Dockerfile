# Build from the repo root: docker build -f deploy/Dockerfile -t coldshock-demo .
FROM python:3.11-slim
WORKDIR /srv
COPY deploy/requirements.txt deploy/requirements.txt
RUN pip install --no-cache-dir -r deploy/requirements.txt
COPY cfd-dashboard/backend cfd-dashboard/backend
COPY cfd-dashboard/frontend cfd-dashboard/frontend
COPY stage1_intake stage1_intake
COPY stage2_optimizer stage2_optimizer
COPY stage3_modelling/coldplate stage3_modelling/coldplate
COPY stage3_modelling/demo stage3_modelling/demo
COPY deploy/server.py deploy/server.py
ENV PORT=8080 DEMO=true LLM_PROVIDER=mock PYTHONUNBUFFERED=1
EXPOSE 8080
CMD ["python", "deploy/server.py"]
