# LiteLLM proxy imajına matriks-pii eklenmiş hâli.
#   docker build -t litellm-matriks-pii -f examples/Dockerfile .
#   docker run -p 4000:4000 -e OPENAI_API_KEY=... -e LITELLM_MASTER_KEY=... litellm-matriks-pii
# Sürüm sabitlenir (main-stable kayan etikettir). matriks-pii LiteLLM 1.106.1, 1.106.5 ve 1.110.2 ile test edildi (asgari 1.106.1).
FROM ghcr.io/berriai/litellm:v1.106.5

COPY . /opt/matriks-pii
# Resmî imajın sanal ortamında (/app/.venv) pip yoktur; ensurepip ile kurulur.
RUN python -m ensurepip >/dev/null \
 && python -m pip install --no-cache-dir "/opt/matriks-pii[fast,metrics]" -c /opt/matriks-pii/constraints/prod.txt
COPY examples/config.yaml /app/config.yaml

ENV PYTHONUTF8=1
# kurulum doğrulaması: config + depo + kanonik sondajlar (< 2 sn). Kubernetes'te startupProbe olarak da kullanılabilir.
HEALTHCHECK --interval=60s --timeout=10s --start-period=30s \
  CMD python -m matriks_pii.selftest --config /app/config.yaml --quick || exit 1
# root olmayan kullanıcı (audit_log yolu bu kullanıcıya yazılabilir olmalı). İmaj Wolfi tabanlıdır: BusyBox adduser.
RUN adduser -D -H -u 10001 litellm && mkdir -p /var/log/litellm && chown -R 10001 /var/log/litellm /app
USER 10001
CMD ["--config", "/app/config.yaml", "--port", "4000"]
