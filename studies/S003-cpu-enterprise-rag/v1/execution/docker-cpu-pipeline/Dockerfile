FROM python:3.12.11-slim-bookworm@sha256:519591d6871b7bc437060736b9f7456b8731f1499a57e22e6c285135ae657bf7

RUN python -m pip install --no-cache-dir \
    --index-url https://download.pytorch.org/whl/cpu \
    torch==2.13.0

RUN python -m pip install --no-cache-dir \
    numpy==2.5.2 \
    onnxruntime==1.29.0 \
    psutil==7.2.2 \
    safetensors==0.8.0 \
    transformers==4.57.6

ENV HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    TOKENIZERS_PARALLELISM=false \
    PYTHONDONTWRITEBYTECODE=1
