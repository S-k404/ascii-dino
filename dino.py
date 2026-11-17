#!/usr/bin/env python3
"""ASCII Dino - a terminal Chrome-Dino-style endless runner (curses)."""
import curses
import locale
import random
import sys
import time
import os

FPS = 120
FRAME_TIME = 1.0 / FPS
# Physics/speed constants are in units-per-second (not per-frame) and every
# update multiplies by FRAME_TIME, so raising FPS yields more, smaller steps
# - i.e. smoother motion - at the same real-world speed rather than a faster
# game. These are the old 30fps-tuned per-frame numbers converted to
# per-second: velocities scale by FPS (30), but GRAVITY is an acceleration
# (rows/frame^2 -> rows/sec^2) so it scales by FPS^2.
GRAVITY = 225.0
JUMP_VELOCITY = 66.0
GROUND_MARGIN_BOTTOM = 3
DINO_COL = 3
# Animation cadences, derived from FPS rather than hardcoded, so they keep
# the same real-world timing (originally tuned as 5 and 10 frames at 30fps)
# regardless of FPS: legs swap every 1/6s, bird wings every 1/3s.
LEG_ANIM_HALF_PERIOD = max(1, round(FPS / 6))
BIRD_FLAP_HALF_PERIOD = max(1, round(FPS / 3))
# HIGHSCORE_FILE moves the saved score (the Docker image points it at a folder you can mount as a volume)
HIGH_SCORE_FILE = os.environ.get("HIGHSCORE_FILE") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "highscore.txt")

DIFFICULTIES = {
    "1": {"name": "EASY", "base_speed": 24.0, "max_speed": 60.0, "speed_ramp": 0.0075,
          "min_gap": 48, "max_gap": 78, "bird_unlock": 350},
    "2": {"name": "NORMAL", "base_speed": 30.0, "max_speed": 84.0, "speed_ramp": 0.0105,
          "min_gap": 66, "max_gap": 100, "bird_unlock": 260},
    "3": {"name": "HARD", "base_speed": 39.0, "max_speed": 108.0, "speed_ramp": 0.015,
          "min_gap": 84, "max_gap": 120, "bird_unlock": 150},
}
DIFFICULTY_ORDER = ["1", "2", "3"]
# min_gap above is chosen so that even at each difficulty's max_speed, the time
# between obstacle spawns comfortably exceeds one full jump-and-land cycle -
# otherwise a second obstacle can arrive before the dino finishes landing from
# the first jump, making it uncleareable no matter how well it's timed.
# The wide cactus cluster takes longer to cross than a jump can stay airborne
# for at low speed, so it's only allowed in once the game is fast enough to
# clear it (see spawn_obstacles).
CLUSTER_MIN_SPEED = 54.0

# Pixel-accurate reproduction of Chrome's offline T-Rex sprite (the dinosaur
# shown when there's no internet), downscaled from the original 44x47 art.
# This is the ground truth silhouette - kept as plain half-block source so
# it's easy to read/edit - which is then decoded to real pixels, upscaled,
# and re-packed into braille glyphs below. Braille packs a 2(wide)x4(tall)
# sub-pixel grid per terminal cell (vs. 1x2 for half-blocks), so the same
# silhouette renders with roughly 4x the edge resolution: smoother diagonals
# on the back/tail/snout instead of blocky half-block steps.
_STAND_SRC = [
    "          ▄████████▄",
    "          ██  ██████",
    "          ██████████",
    "         ▄████▄▄▄▄",
    "      ▄▄██████",
    "▄▄████████████▄",
    "▀▀▀▀███████████▀",
    "     ███▀▀███",
    "     ███  ███▄",
    "     ███▄",
]
_STAND_ALT_SRC = [
    "          ▄████████▄",
    "          ██  ██████",
    "          ██████████",
    "         ▄████▄▄▄▄",
    "      ▄▄██████",
    "▄▄████████████▄",
    "▀▀▀▀███████████▀",
    "     ███▀▀███",
    "    ▄███  ███",
    "          ███▄",
]
_DUCK_SRC = [
    "                 ▄███████▄",
    "                 ██  █████",
    "                ▄████▄▄▄▄",
    "▄▄████████████████████▀",
    " ▀▀▀▀███▀▀▀███▀▀▀▀",
    "     ███▄  ███▄",
]
_DUCK_ALT_SRC = [
    "                 ▄███████▄",
    "                 ██  █████",
    "                ▄████▄▄▄▄",
    "▄▄████████████████████▀",
    " ▀▀▀▀███▀▀▀███▀▀▀▀",
    "    ▄███  ▄███",
]

_BRAILLE_BITS = {(0, 0): 0x01, (0, 1): 0x02, (0, 2): 0x04, (0, 3): 0x40,
                  (1, 0): 0x08, (1, 1): 0x10, (1, 2): 0x20, (1, 3): 0x80}


def _decode_half_block(lines):
    w = max(len(line) for line in lines)
    grid = []
    for line in lines:
        top = [False] * w
        bot = [False] * w
        for x, ch in enumerate(line):
            if ch == "▄":
                bot[x] = True
            elif ch == "▀":
                top[x] = True
            elif ch == "█":
                top[x] = True
                bot[x] = True
        grid.append(top)
        grid.append(bot)
    return grid


def _upscale2x(grid):
    h, w = len(grid), len(grid[0])
    out = [[False] * (w * 2) for _ in range(h * 2)]
    for y in range(h):
        for x in range(w):
            if grid[y][x]:
                out[y * 2][x * 2] = out[y * 2][x * 2 + 1] = True
                out[y * 2 + 1][x * 2] = out[y * 2 + 1][x * 2 + 1] = True
    return out


def _pack_braille(grid):
    h, w = len(grid), len(grid[0])
    lines = []
    for cy in range(0, h, 4):
        row = []
        for cx in range(0, w, 2):
            val = 0
            for (dx, dy), bit in _BRAILLE_BITS.items():
                if grid[cy + dy][cx + dx]:
                    val |= bit
            row.append(chr(0x2800 + val))
        lines.append("".join(row))
    return lines


def _braille_sprite(src):
    return _pack_braille(_upscale2x(_decode_half_block(src)))


DINO_STAND = _braille_sprite(_STAND_SRC)
DINO_STAND_ALT = _braille_sprite(_STAND_ALT_SRC)
DINO_DUCK = _braille_sprite(_DUCK_SRC)
DINO_DUCK_ALT = _braille_sprite(_DUCK_ALT_SRC)
STAND_HEIGHT = len(DINO_STAND)

# Collision hitbox: a single rect (this game only tracks one, unlike Chrome's
# four) positioned to match Chrome's own "legs" collision box - (x=5, y=14,
# w=9, h=6 in its 21x20 sprite; halved here since only rows are downscaled).
# A box this tight (rather than the full glyph) is intentional: Chrome itself
# splits the dino into several boxes because one rectangle around the whole
# sprite is mostly empty space (snout top-right, tail root left) and would
# make corner grazes feel unfair. (left_offset, width, top_offset, height),
# all in glyph-local coordinates - unaffected by the braille re-render since
# it preserves the source glyphs' exact character-grid dimensions.
STAND_HITBOX = (5, 9, 7, 3)
DUCK_HITBOX = (1, 20, 3, 3)

SMALL_CACTUS = [" Y ", "\\|/", " | "]
TALL_CACTUS = [" Y ", "\\|/", " | ", "\\|/"]
CACTUS_CLUSTER = [" Y   Y ", "\\|/ \\|/", " |   | "]
# Pixel-accurate reproduction of Chrome's pterodactyl, same technique as the dino.
BIRD_A = [
    "     \u2584\u2588\u2588\u2588\u2588\u2588",
    "   \u2584\u2588\u2588\u2588\u2588\u2588\u2580",
    "\u2584\u2584\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2584 \u2584\u2584\u2584\u2584",
    "\u2580\u2580\u2580\u2580\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2580\u2580\u2580",
    "     \u2580\u2588\u2588\u2588\u2580",
]
BIRD_B = [
    "     \u2584\u2588\u2588\u2588\u2584",
    "\u2584\u2584\u2584\u2584\u2588\u2588\u2588\u2588\u2588\u2580\u2588\u2584\u2584\u2584",
    "\u2580\u2580\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2580\u2580\u2580\u2580\u2580",
    "   \u2580\u2588\u2588\u2588\u2588\u2588\u2584",
    "     \u2580\u2588\u2588\u2588\u2588\u2588",
]

BASE_OBSTACLE_ART = [SMALL_CACTUS, TALL_CACTUS]


def load_high_score():
    try:
        with open(HIGH_SCORE_FILE) as f:
            return int(f.read().strip() or 0)
    except (OSError, ValueError):
        return 0


def save_high_score(score):
    try:
        with open(HIGH_SCORE_FILE, "w") as f:
            f.write(str(int(score)))
    except OSError:
        pass


def rects_overlap(a_left, a_right, a_top, a_bottom, b_left, b_right, b_top, b_bottom):
    if a_right < b_left or a_left > b_right:
        return False
    if a_bottom < b_top or a_top > b_bottom:
        return False
    return True


def safe_addstr(stdscr, row, col, text, attr=0):
    height, width = stdscr.getmaxyx()
    if row < 0 or row >= height or col >= width:
        return
    if col < 0:
        text = text[-col:]
        col = 0
    max_len = width - col
    if max_len <= 0:
        return
    try:
        stdscr.addstr(row, col, text[:max_len], attr)
    except curses.error:
        pass


class Game:
    def __init__(self, stdscr):
        self.stdscr = stdscr
        self.high_score = load_high_score()
        self.use_color = curses.has_colors()
        if self.use_color:
            curses.start_color()
            curses.use_default_colors()
            curses.init_pair(1, curses.COLOR_GREEN, -1)
            curses.init_pair(2, curses.COLOR_RED, -1)
            curses.init_pair(3, curses.COLOR_YELLOW, -1)
            curses.init_pair(4, curses.COLOR_CYAN, -1)
        self.difficulty_key = "2"
        self.auto_mode = False
        self.state = "menu"
        self.reset()

    def reset(self):
        diff = DIFFICULTIES[self.difficulty_key]
        self.base_speed = diff["base_speed"]
        self.max_speed = diff["max_speed"]
        self.speed_ramp = diff["speed_ramp"]
        self.min_gap = diff["min_gap"]
        self.max_gap = diff["max_gap"]
        self.bird_unlock = diff["bird_unlock"]

        self.dino_y = 0.0
        self.velocity = 0.0
        self.ducking = False
        self.obstacles = []
        self.distance_since_last = 0.0
        self.next_gap = random.randint(self.min_gap, self.max_gap)
        self.score = 0.0
        self.tick = 0
        self.speed = self.base_speed

    def ground_row(self, height):
        return height - GROUND_MARGIN_BOTTOM

    def dino_art_and_size(self):
        alt = self.tick % (2 * LEG_ANIM_HALF_PERIOD) < LEG_ANIM_HALF_PERIOD
        if self.ducking and self.dino_y == 0:
            art = DINO_DUCK_ALT if alt else DINO_DUCK
        else:
            art = DINO_STAND_ALT if alt else DINO_STAND
        h = len(art)
        w = max(len(line) for line in art)
        return art, h, w

    def update_physics(self):
        if self.dino_y > 0 or self.velocity != 0:
            self.dino_y += self.velocity * FRAME_TIME
            self.velocity -= GRAVITY * FRAME_TIME
            if self.dino_y <= 0:
                self.dino_y = 0.0
                self.velocity = 0.0

    def spawn_obstacles(self, width):
        self.distance_since_last += self.speed * FRAME_TIME
        if self.distance_since_last >= self.next_gap:
            self.distance_since_last = 0
            self.next_gap = random.randint(
                max(self.min_gap, self.max_gap - int(self.speed * 8 / 30)), self.max_gap
            )
            if self.score > self.bird_unlock and random.random() < 0.3:
                self.obstacles.append(
                    {"col": float(width), "type": "bird", "flap": 0,
                     "lines_a": BIRD_A, "lines_b": BIRD_B}
                )
            else:
                pool = BASE_OBSTACLE_ART
                if self.speed >= CLUSTER_MIN_SPEED:
                    pool = BASE_OBSTACLE_ART + [CACTUS_CLUSTER]
                lines = random.choice(pool)
                self.obstacles.append(
                    {"col": float(width), "type": "cactus", "lines": lines}
                )

    def update_obstacles(self, width):
        for obs in self.obstacles:
            obs["col"] -= self.speed * FRAME_TIME
            if obs["type"] == "bird":
                obs["flap"] = (obs["flap"] + 1) % (2 * BIRD_FLAP_HALF_PERIOD)
        self.obstacles = [o for o in self.obstacles if o["col"] > -12]

    def obstacle_rect(self, obs, ground_row):
        if obs["type"] == "cactus":
            lines = obs["lines"]
            h = len(lines)
            w = max(len(l) for l in lines)
            bottom = ground_row - 1
        else:
            lines = obs["lines_a"]
            h = len(lines)
            w = max(len(l) for l in lines)
            bottom = ground_row - 1 - STAND_HEIGHT
        top = bottom - h + 1
        left = int(obs["col"])
        right = left + w - 1
        return left, right, top, bottom

    def dino_hitbox(self, ground_row):
        _, dino_h, dino_w = self.dino_art_and_size()
        if self.ducking and self.dino_y == 0:
            left_off, hb_w, top_off, hb_h = DUCK_HITBOX
        else:
            left_off, hb_w, top_off, hb_h = STAND_HITBOX
        hb_h = min(hb_h, dino_h - top_off)
        glyph_bottom = ground_row - 1 - int(self.dino_y)
        glyph_top = glyph_bottom - dino_h + 1
        top = glyph_top + top_off
        bottom = top + hb_h - 1
        left = DINO_COL + left_off
        right = left + hb_w - 1
        return left, right, top, bottom

    def check_collision(self, ground_row):
        dino_left, dino_right, dino_top, dino_bottom = self.dino_hitbox(ground_row)
        for obs in self.obstacles:
            obs_left, obs_right, obs_top, obs_bottom = self.obstacle_rect(obs, ground_row)
            if rects_overlap(
                dino_left, dino_right, dino_top, dino_bottom,
                obs_left, obs_right, obs_top, obs_bottom,
            ):
                return True
        return False

    def autoplay_step(self, ground_row):
        _, dino_right, _, _ = self.dino_hitbox(ground_row)
        nearest = None
        for obs in self.obstacles:
            obs_left, obs_right, _, _ = self.obstacle_rect(obs, ground_row)
            if obs_right >= dino_right and (nearest is None or obs_left < nearest[0]):
                nearest = (obs_left, obs)

        if nearest is None:
            self.ducking = False
            return

        obs_left, obs = nearest
        gap = obs_left - dino_right
        if obs["type"] == "bird":
            duck_lead = max(4, int(self.speed / 6))
            self.ducking = 0 <= gap <= duck_lead
        else:
            self.ducking = False
            jump_lead = max(3, int(self.speed / 10))
            if self.dino_y == 0 and 0 <= gap <= jump_lead:
                self.velocity = JUMP_VELOCITY

    def draw_menu(self):
        stdscr = self.stdscr
        height, width = stdscr.getmaxyx()
        stdscr.erase()
        cy = height // 2
        title = "A S C I I   D I N O"
        safe_addstr(stdscr, max(0, cy - 5), max(0, (width - len(title)) // 2), title, curses.A_BOLD)

        lines = []
        for key in DIFFICULTY_ORDER:
            diff = DIFFICULTIES[key]
            marker = ">" if key == self.difficulty_key else " "
            lines.append(f"{marker} [{key}] {diff['name']}")
        auto_line = f"  [A] Auto-Play: {'ON' if self.auto_mode else 'OFF'}"
        start_line = "  Press SPACE / ENTER to start"
        quit_line = "  Press Q to quit"

        row = cy - 2
        for line in lines:
            attr = curses.A_BOLD if line.startswith(">") else 0
            safe_addstr(stdscr, row, max(0, (width - 20) // 2), line, attr)
            row += 1
        row += 1
        safe_addstr(stdscr, row, max(0, (width - 20) // 2), auto_line)
        row += 2
        safe_addstr(stdscr, row, max(0, (width - len(start_line)) // 2), start_line, curses.A_DIM)
        row += 1
        safe_addstr(stdscr, row, max(0, (width - len(quit_line)) // 2), quit_line, curses.A_DIM)

        hs_line = f"High Score: {int(self.high_score):05d}"
        safe_addstr(stdscr, row + 2, max(0, (width - len(hs_line)) // 2), hs_line)

        stdscr.refresh()

    def draw(self):
        stdscr = self.stdscr
        height, width = stdscr.getmaxyx()
        stdscr.erase()
        ground_row = self.ground_row(height)

        ground_attr = curses.color_pair(4) if self.use_color else 0
        safe_addstr(stdscr, ground_row, 0, "_" * width, ground_attr)

        cactus_attr = curses.color_pair(1) if self.use_color else 0
        bird_attr = curses.color_pair(2) if self.use_color else 0
        for obs in self.obstacles:
            col = int(obs["col"])
            if obs["type"] == "cactus":
                lines = obs["lines"]
                bottom = ground_row - 1
                top = bottom - len(lines) + 1
                for i, line in enumerate(lines):
                    safe_addstr(stdscr, top + i, col, line, cactus_attr)
            else:
                lines = obs["lines_a"] if obs["flap"] < BIRD_FLAP_HALF_PERIOD else obs["lines_b"]
                bottom = ground_row - 1 - STAND_HEIGHT
                top = bottom - len(lines) + 1
                for i, line in enumerate(lines):
                    safe_addstr(stdscr, top + i, col, line, bird_attr)

        art, dino_h, dino_w = self.dino_art_and_size()
        dino_attr = curses.color_pair(3) if self.use_color else 0
        bottom = ground_row - 1 - int(self.dino_y)
        top = bottom - dino_h + 1
        for i, line in enumerate(art):
            safe_addstr(stdscr, top + i, DINO_COL, line, dino_attr)

        diff_name = DIFFICULTIES[self.difficulty_key]["name"]
        auto_tag = "  [AUTO]" if self.auto_mode else ""
        score_text = f"Score: {int(self.score):05d}   High: {int(self.high_score):05d}   {diff_name}{auto_tag}"
        safe_addstr(stdscr, 0, max(0, width - len(score_text) - 2), score_text, curses.A_BOLD)
        safe_addstr(stdscr, 0, 2, "ASCII DINO", curses.A_BOLD)
        safe_addstr(stdscr, height - 1, 2, "SPACE/UP jump  DOWN duck  A auto  Q quit", curses.A_DIM)

        if self.state == "game_over":
            msg1 = "GAME OVER"
            msg2 = f"Score: {int(self.score)}   High: {int(self.high_score)}"
            msg3 = "R restart   M menu   Q quit"
            cy = height // 2
            safe_addstr(stdscr, cy - 1, max(0, (width - len(msg1)) // 2), msg1, curses.A_BOLD | curses.A_REVERSE)
            safe_addstr(stdscr, cy, max(0, (width - len(msg2)) // 2), msg2)
            safe_addstr(stdscr, cy + 1, max(0, (width - len(msg3)) // 2), msg3)

        stdscr.refresh()

    def run(self):
        stdscr = self.stdscr
        while True:
            frame_start = time.time()
            height, width = stdscr.getmaxyx()

            if self.state == "menu":
                while True:
                    ch = stdscr.getch()
                    if ch == -1:
                        break
                    key = chr(ch) if 0 <= ch < 256 else ""
                    if key in DIFFICULTY_ORDER:
                        self.difficulty_key = key
                    elif key in ("a", "A"):
                        self.auto_mode = not self.auto_mode
                    elif ch in (ord(" "), 10, 13, curses.KEY_ENTER):
                        self.reset()
                        self.state = "playing"
                    elif key in ("q", "Q"):
                        return
                self.draw_menu()

            elif self.state == "playing":
                held_down = False
                jump_requested = False
                while True:
                    ch = stdscr.getch()
                    if ch == -1:
                        break
                    key = chr(ch) if 0 <= ch < 256 else ""
                    if ch in (curses.KEY_UP, ord(" ")) or key in ("w", "W"):
                        jump_requested = True
                    elif ch == curses.KEY_DOWN or key in ("s", "S"):
                        held_down = True
                    elif key in ("a", "A"):
                        self.auto_mode = not self.auto_mode
                    elif key in ("q", "Q"):
                        return

                ground_row = self.ground_row(height)

                if self.auto_mode:
                    self.autoplay_step(ground_row)
                else:
                    self.ducking = held_down
                    if jump_requested and self.dino_y == 0 and not held_down:
                        self.velocity = JUMP_VELOCITY

                self.update_physics()
                self.speed = min(self.max_speed, self.base_speed + self.score * self.speed_ramp)
                self.spawn_obstacles(width)
                self.update_obstacles(width)
                self.score += self.speed * 0.5 * FRAME_TIME
                self.tick += 1

                if self.check_collision(ground_row):
                    self.state = "game_over"
                    if self.score > self.high_score:
                        self.high_score = self.score
                        save_high_score(self.high_score)

                self.draw()

            elif self.state == "game_over":
                while True:
                    ch = stdscr.getch()
                    if ch == -1:
                        break
                    key = chr(ch) if 0 <= ch < 256 else ""
                    if key in ("r", "R"):
                        self.reset()
                        self.state = "playing"
                    elif key in ("m", "M"):
                        self.state = "menu"
                    elif key in ("q", "Q"):
                        return
                self.draw()

            elapsed = time.time() - frame_start
            sleep_time = FRAME_TIME - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)


def main(stdscr):
    curses.curs_set(0)
    stdscr.nodelay(True)
    stdscr.keypad(True)
    game = Game(stdscr)
    game.run()


if __name__ == "__main__":
    # Must happen before curses initializes, so it renders the braille and
    # half-block sprite characters (the dino/bird art) as UTF-8 instead of
    # raising on them.
    locale.setlocale(locale.LC_ALL, "")
    if not sys.stdin.isatty():
        # curses needs a real controlling terminal; without one (e.g. `docker
        # run` without -it, or a non-interactive launcher) it fails deep
        # inside cbreak()/nocbreak() with a confusing traceback - catch it
        # here with a message that says what to actually do instead.
        print(
            "ASCII Dino needs an interactive terminal to run.\n"
            "Run it with: docker run -it --rm ascii-dino\n"
            "(or `python3 dino.py` directly in a real terminal)",
            file=sys.stderr,
        )
        sys.exit(1)
    curses.wrapper(main)
