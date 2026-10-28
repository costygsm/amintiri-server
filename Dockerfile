FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY poze ./poze
COPY tests ./tests
# testele rulează aici, pe 3.12; imaginea nu se construiește dacă pică (clipurile: PyAV, fără ffmpeg în sistem)
RUN pip install --no-cache-dir '.[dev]' \
    && python -m pytest -q -p no:cacheprovider tests && rm -rf tests
ENV PYTHONUNBUFFERED=1 TZ=Europe/Bucharest POZE_DATA_DIR=/data POZE_PORT=8090 POZE_HOST=127.0.0.1
# un singur worker: blocările uploadurilor sunt în memorie
CMD ["sh", "-c", "exec uvicorn poze.app:app --host ${POZE_HOST} --port ${POZE_PORT} --workers 1 --proxy-headers --forwarded-allow-ips 127.0.0.1"]
