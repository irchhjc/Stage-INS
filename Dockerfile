FROM python:3.14.7-slim-trixie AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build
RUN python -m venv /opt/venv
COPY requirements-prod.txt .
RUN /opt/venv/bin/pip install --upgrade pip \
    && /opt/venv/bin/pip install -r requirements-prod.txt


FROM python:3.14.7-slim-trixie

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --create-home --shell /usr/sbin/nologin app

WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY --chown=app:app app ./app
COPY --chown=app:app config.py run.py ./
RUN mkdir -p /app/instance/uploads /app/instance/exports /app/instance/logs \
    && chown -R app:app /app/instance

USER app
EXPOSE 8000

CMD ["gunicorn", "run:app", "--bind", "0.0.0.0:8000", "--worker-class", "gthread", "--workers", "2", "--threads", "4", "--timeout", "600", "--graceful-timeout", "60", "--worker-tmp-dir", "/dev/shm", "--access-logfile", "-", "--error-logfile", "-"]
