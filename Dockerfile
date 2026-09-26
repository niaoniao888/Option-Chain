FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/src \
    OPTIONS_APP_ROOT=/app OPTIONS_HOST=0.0.0.0 OPTIONS_PORT=8780 \
    OPTIONS_RUNTIME_DIR=/app/runtime
WORKDIR /app
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock && \
    groupadd --gid 10001 panel && useradd --uid 10001 --gid panel --no-create-home panel
COPY src ./src
COPY web ./web
COPY content ./content
RUN mkdir -p runtime && chown panel:panel runtime
USER panel
EXPOSE 8780
STOPSIGNAL SIGTERM
CMD ["python", "-m", "options_panel"]
