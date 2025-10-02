# syntax=docker/dockerfile:1.4

# ---------------------------
# Stage 1: Builder (Python slim)
# ---------------------------
FROM python:3.13-slim AS builder

WORKDIR /app

# Copy requirements
COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY src/*.py ./

# 12-factor environment variables
ENV PYTHONUNBUFFERED=1 \
    NAMESPACE=default \
    POD_NAME="" \
    NODE_SOCKET=/ipc/node.socket \
    SOURCE_KES_KEY=/secrets/kes.skey \
    SOURCE_VRF_KEY=/secrets/vrf.skey \
    SOURCE_OP_CERT=/secrets/node.cert \
    TARGET_KES_KEY=/opt/cardano/secrets/kes.skey \
    TARGET_VRF_KEY=/opt/cardano/secrets/vrf.skey \
    TARGET_OP_CERT=/opt/cardano/secrets/node.cert \
    LEASE_NAME=cardano-node-leader \
    CRD_GROUP=cardano.io \
    CRD_VERSION=v1 \
    CRD_PLURAL=cardanoleaders \
    CRD_NAME=cardano-leader \
    METRICS_PORT=8000 \
    SOCKET_WAIT_TIMEOUT=600 \
    SLEEP_INTERVAL=5 \
    LOG_LEVEL=INFO \
    START_AS_NON_PRODUCING=true

EXPOSE 8000

# Entrypoint: run your script
ENTRYPOINT ["python", "-m", "forgemanager"]
