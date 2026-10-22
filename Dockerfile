FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt \
    && groupadd --gid 10001 beton \
    && useradd --uid 10001 --gid beton --no-create-home --shell /usr/sbin/nologin beton \
    && mkdir -p /data \
    && chown beton:beton /data

COPY --chown=beton:beton backend ./backend
COPY --chown=beton:beton games_5_7.html ./games_5_7.html

USER 10001:10001
EXPOSE 8000

CMD ["gunicorn", "--workers", "2", "--bind", "0.0.0.0:8000", "--access-logfile", "-", "--error-logfile", "-", "backend.app:app"]