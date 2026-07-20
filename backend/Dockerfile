FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

ARG RELEASE_COMMIT
RUN test -n "$RELEASE_COMMIT" \
    && printf '%s' "$RELEASE_COMMIT" | grep -Eq '^[0-9a-f]{40}$' \
    && printf '%s\n' "$RELEASE_COMMIT" > /app/RELEASE_COMMIT \
    && chown root:root /app/RELEASE_COMMIT \
    && chmod 0444 /app/RELEASE_COMMIT

COPY pyproject.toml ./
RUN pip install --no-cache-dir -e .

COPY app ./app
COPY scripts ./scripts

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
