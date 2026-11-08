FROM python:3.12-slim

ENV TERM=xterm-256color \
    PYTHONUNBUFFERED=1 \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8

WORKDIR /app
COPY dino.py .

ENTRYPOINT ["python3", "dino.py"]
