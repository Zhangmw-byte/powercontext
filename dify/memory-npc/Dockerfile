FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    POWERCONTEXT_HOME=/data

WORKDIR /srv/npc-memory

COPY requirements.lock /srv/npc-memory/requirements.lock
RUN pip install --no-cache-dir -r requirements.lock

COPY pyproject.toml /srv/npc-memory/
COPY app /srv/npc-memory/app
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

EXPOSE 8877
ENTRYPOINT ["docker-entrypoint.sh"]
