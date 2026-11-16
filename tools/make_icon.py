"""Draw the app icon (a yellow brick with a dark IR window) and write rcxtower/data/rcxtower.ico.

Pure standard library. Run: python tools/make_icon.py
"""
import os
import struct

YELLOW = (255, 205, 0)
EDGE = (176, 132, 0)
WINDOW = (40, 34, 46)
RED = (226, 40, 40)
GLOW = (255, 150, 150)


def pixel(x, y, n):
    """Colour (r, g, b, a) of the pixel centre at x, y in an n x n icon."""
    u, v = (x + 0.5) / n, (y + 0.5) / n
    r = 0.16  # corner radius of the body
    lo, hi = 0.06, 0.94
    if not (lo <= u <= hi and lo <= v <= hi):
        return (0, 0, 0, 0)
    cx = min(max(u, lo + r), hi - r)
    cy = min(max(v, lo + r), hi - r)
    d = ((u - cx) ** 2 + (v - cy) ** 2) ** 0.5
    if d > r:
        return (0, 0, 0, 0)
    edge = d > r - 0.07 or u < lo + 0.07 or u > hi - 0.07 or v < lo + 0.07 or v > hi - 0.07
    colour = EDGE if edge else YELLOW
    if 0.20 <= u <= 0.80 and 0.22 <= v <= 0.56:  # IR window
        colour = WINDOW
        dist = ((u - 0.5) ** 2 + (v - 0.39) ** 2) ** 0.5
        if dist < 0.06:
            colour = GLOW
        elif dist < 0.12:
            colour = RED
    elif 0.66 <= v <= 0.80 and (abs(u - 0.32) < 0.07 or abs(u - 0.68) < 0.07):  # two studs
        colour = EDGE
    return colour + (255,)


def image(n):
    rows = []
    for y in range(n - 1, -1, -1):  # bitmap rows are bottom-up
        row = bytearray()
        for x in range(n):
            r, g, b, a = pixel(x, y, n)
            row += bytes((b, g, r, a))
        rows.append(bytes(row))
    mask_row = b"\0" * (((n + 31) // 32) * 4)
    header = struct.pack("<IiiHHIIiiII", 40, n, n * 2, 1, 32, 0, 0, 0, 0, 0, 0)
    return header + b"".join(rows) + mask_row * n


def main():
    sizes = (16, 24, 32, 48, 64)
    images = [image(n) for n in sizes]
    out = struct.pack("<HHH", 0, 1, len(sizes))
    offset = 6 + 16 * len(sizes)
    for n, data in zip(sizes, images):
        out += struct.pack("<BBBBHHII", n, n, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    out += b"".join(images)
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "rcxtower", "data", "rcxtower.ico")
    with open(path, "wb") as f:
        f.write(out)
    print("wrote", os.path.normpath(path), len(out), "bytes")


if __name__ == "__main__":
    main()
