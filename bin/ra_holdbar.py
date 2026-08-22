#!/usr/bin/env python3
"""The "hold to exit" bar drawn over a running game, driven over stdin.

A separate process on purpose. SDL wants its video calls on the process's main
thread, and the launcher is busy supervising RetroArch; running the window here
means a wedged or crashed overlay can never take a game down with it.

Protocol, one line at a time:
    0.42        show the bar, 42% of the way to quitting
    hide        take it away
    EOF         exit

It is a full-width strip along the bottom edge deliberately: an ordinary
always-on-top window makes xfwm4 stop treating RetroArch as an unredirected
fullscreen window, which lets the XFCE panel pop out over the game. Covering
that strip hides the panel behind the bar instead of fighting it.
"""

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "x11")
os.environ.setdefault("DISPLAY", ":0")
# pause_nonactive is on: a window that takes focus would pause the very game
# this is drawn over.
os.environ["SDL_WINDOW_NO_ACTIVATION_WHEN_SHOWN"] = "1"

import pygame
from pygame._sdl2.video import Window, Renderer, Texture

FONT = "/home/retro/.local/share/fonts/PressStart2P.ttf"
HEIGHT = 104
BG = (16, 14, 40)
EDGE = (255, 62, 165)
TEXT = (255, 212, 71)
TRACK = (122, 111, 192)
FILL = (70, 232, 244)


class Bar:
    def __init__(self):
        self.window = None
        self.renderer = None
        self.width = 1920
        pygame.init()
        pygame.font.init()
        self.font = pygame.font.Font(FONT if os.path.exists(FONT) else None, 22)

    def open(self):
        if self.window is not None:
            return
        info = pygame.display.Info()
        self.width = info.current_w or 1920
        top = (info.current_h or 1080) - HEIGHT
        self.window = Window("ra-holdbar", size=(self.width, HEIGHT),
                             position=(0, top), borderless=True,
                             always_on_top=True)
        self.renderer = Renderer(self.window)
        # No taskbar or pager entry: this is a heads-up, not an application.
        os.system("wmctrl -r ra-holdbar -b add,skip_taskbar,skip_pager,above"
                  " >/dev/null 2>&1")

    def close(self):
        if self.window is None:
            return
        self.window.destroy()
        self.window = None
        self.renderer = None

    def draw(self, fraction):
        self.open()
        surface = pygame.Surface((self.width, HEIGHT))
        surface.fill(BG)
        pygame.draw.rect(surface, EDGE, (0, 0, self.width, 4))
        label = self.font.render("HOLD TO EXIT", True, TEXT)
        surface.blit(label, ((self.width - label.get_width()) // 2, 24))
        bw = min(700, self.width // 2)
        bx, by, bh = (self.width - bw) // 2, 64, 22
        pygame.draw.rect(surface, TRACK, (bx, by, bw, bh), 2)
        filled = max(0, min(bw - 6, int((bw - 6) * fraction)))
        if filled:
            pygame.draw.rect(surface, FILL, (bx + 3, by + 3, filled, bh - 6))
        texture = Texture.from_surface(self.renderer, surface)
        self.renderer.clear()
        self.renderer.blit(texture)
        self.renderer.present()


def main():
    bar = Bar()
    try:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            if line == "hide":
                bar.close()
                continue
            try:
                bar.draw(max(0.0, min(1.0, float(line))))
            except ValueError:
                pass
    except (KeyboardInterrupt, OSError):
        pass
    finally:
        bar.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
