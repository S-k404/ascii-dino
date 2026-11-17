FROM python:3.12-slim

ENV TERM=xterm-256color \
    PYTHONUNBUFFERED=1 \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8

WORKDIR /app
COPY dino.py .

# Mount a volume on /data to keep your high score between runs
RUN mkdir -p /data
ENV HIGHSCORE_FILE=/data/highscore.txt

ENTRYPOINT ["python3", "dino.py"]
