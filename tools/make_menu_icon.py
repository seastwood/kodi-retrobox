#!/usr/bin/env python3
"""Draw the Fourth Player menu tile.

Matched to the icons this console already ships rather than invented: 256
square, a filled #121634 disc inside a #46E8F4 ring, outer radius 120 and the
ring 24 thick, hard edges and no anti-aliasing. Two colours and transparency,
which is what every other tile on that menu is made of.

The entry used the MULTIPLAYER icon, so the two rows were the same picture.
They are not the same thing: multiplayer is who is on the sofa, Fourth Player
is somebody who is not in the building. Hence a numeral rather than more
gamepads -- this is the fourth pad, the one that arrives from somewhere else,
and a digit reads across a room where a third small controller would not.
"""
import sys

from PIL import Image

SIZE = 256
MID = SIZE // 2
OUTER = 120
RING = 24
CYAN = (70, 232, 244, 255)
DARK = (18, 22, 52, 255)
CLEAR = (0, 0, 0, 0)


def disc():
    image = Image.new("RGBA", (SIZE, SIZE), CLEAR)
    pixels = image.load()
    for y in range(SIZE):
        for x in range(SIZE):
            dx, dy = x - MID + 0.5, y - MID + 0.5
            away = (dx * dx + dy * dy) ** 0.5
            if away <= OUTER - RING:
                pixels[x, y] = DARK
            elif away <= OUTER:
                pixels[x, y] = CYAN
    return image


def block(pixels, x0, y0, x1, y1, colour=CYAN):
    for y in range(max(0, y0), min(SIZE, y1)):
        for x in range(max(0, x0), min(SIZE, x1)):
            pixels[x, y] = colour


def four(image):
    pixels = image.load()
    # A blocky 4, thick enough to read across a room.
    block(pixels, 74, 64, 100, 152)        # the down stroke
    block(pixels, 74, 152, 176, 176)       # the crossbar
    block(pixels, 150, 64, 176, 208)       # the long stroke
    return image


if __name__ == "__main__":
    four(disc()).save(sys.argv[1] if len(sys.argv) > 1 else "_fourthplayer.png")
    print("wrote it")
