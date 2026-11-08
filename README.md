# ASCII Dino

A terminal Chrome-Dino-style endless runner, written in Python (`curses`) and containerized with Docker.

## Run with Docker

```sh
docker build -t ascii-dino .
docker run -it --rm ascii-dino
```

`-it` is required so the container gets an interactive TTY for keyboard input.

## Run locally (no Docker)

```sh
python3 dino.py
```

Requires Python 3 with `curses` (built in on macOS/Linux).

## Controls

- `SPACE` / `UP` / `W` — jump
- `DOWN` / `S` — duck (dodge low-flying birds)
- `R` — restart after game over
- `Q` — quit

High score is saved to `highscore.txt` next to the script.
