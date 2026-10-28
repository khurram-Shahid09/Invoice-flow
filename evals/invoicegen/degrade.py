"""Make a clean page image look scanned or photographed (docs/13 "Degradations for scans").

Scans: grey, slightly rotated, a little blur and speckle, JPEG artefacts.
Photos: perspective tilt, uneven light, warm cast, on a desk-coloured background.
Every effect is driven by the case's own random generator, so output is repeatable.
"""

import io
import random

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps


def _jpeg(image: Image.Image, quality: int) -> Image.Image:
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=quality)
    buffer.seek(0)
    return Image.open(buffer).convert(image.mode)


def _speckle(image: Image.Image, rng: random.Random, amount: int) -> Image.Image:
    draw = ImageDraw.Draw(image)
    w, h = image.size
    for _ in range(amount):
        x, y = rng.randrange(w), rng.randrange(h)
        shade = rng.randint(120, 200)
        draw.point((x, y), fill=shade if image.mode == "L" else (shade,) * 3)
    return image


def scan(page: Image.Image, rng: random.Random) -> Image.Image:
    image = ImageOps.grayscale(page)
    image = image.rotate(
        rng.uniform(-2.5, 2.5), resample=Image.Resampling.BICUBIC, expand=True, fillcolor=255
    )
    image = image.filter(ImageFilter.GaussianBlur(rng.uniform(0.4, 0.9)))
    image = ImageEnhance.Contrast(image).enhance(rng.uniform(1.1, 1.35))
    image = _speckle(image, rng, amount=image.width * image.height // 4000)
    return _jpeg(image, rng.randint(45, 65))


def _perspective_coeffs(
    src: list[tuple[float, float]], dst: list[tuple[float, float]]
) -> list[float]:
    """Coefficients for Image.transform(PERSPECTIVE) mapping dst corners back to src corners."""
    rows = []
    for (x, y), (u, v) in zip(dst, src, strict=True):
        rows.append([x, y, 1, 0, 0, 0, -u * x, -u * y, u])
        rows.append([0, 0, 0, x, y, 1, -v * x, -v * y, v])
    # Solve the 8x8 system by Gaussian elimination (no numpy needed).
    n = 8
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(rows[r][col]))
        rows[col], rows[pivot] = rows[pivot], rows[col]
        for r in range(n):
            if r != col:
                factor = rows[r][col] / rows[col][col]
                rows[r] = [a - factor * b for a, b in zip(rows[r], rows[col], strict=True)]
    return [rows[i][n] / rows[i][i] for i in range(n)]


def photo(page: Image.Image, rng: random.Random) -> Image.Image:
    page = page.convert("RGB")
    w, h = page.size
    margin = int(w * 0.08)
    canvas = Image.new("RGB", (w + 2 * margin, h + 2 * margin), (96, 78, 62))  # wooden desk
    j = lambda: rng.uniform(0, w * 0.05)  # noqa: E731
    corners = [
        (margin + j(), margin + j()),
        (margin + w - j(), margin + j()),
        (margin + w - j(), margin + h - j()),
        (margin + j(), margin + h - j()),
    ]
    coeffs = _perspective_coeffs([(0, 0), (w, 0), (w, h), (0, h)], corners)
    warped = page.transform(
        canvas.size, Image.Transform.PERSPECTIVE, coeffs, Image.Resampling.BICUBIC
    )
    mask = Image.new("L", page.size, 255).transform(
        canvas.size, Image.Transform.PERSPECTIVE, coeffs, Image.Resampling.BICUBIC
    )
    canvas.paste(warped, (0, 0), mask)

    # Uneven light: a soft shadow from one side.
    shade = Image.new("L", canvas.size, 0)
    draw = ImageDraw.Draw(shade)
    side = rng.choice(["left", "top", "right"])
    for i in range(0, canvas.width if side != "top" else canvas.height, 4):
        alpha = int(70 * max(0.0, 1 - i / (0.6 * canvas.width)))
        if side == "left":
            draw.line([(i, 0), (i, canvas.height)], fill=alpha, width=4)
        elif side == "right":
            draw.line(
                [(canvas.width - i, 0), (canvas.width - i, canvas.height)], fill=alpha, width=4
            )
        else:
            draw.line([(0, i), (canvas.width, i)], fill=alpha, width=4)
    canvas = Image.composite(Image.new("RGB", canvas.size, (0, 0, 0)), canvas, shade)

    warm = Image.new("RGB", canvas.size, (255, 236, 205))
    canvas = Image.blend(canvas, warm, rng.uniform(0.06, 0.12))
    canvas = canvas.filter(ImageFilter.GaussianBlur(rng.uniform(0.5, 1.0)))
    canvas = ImageEnhance.Brightness(canvas).enhance(rng.uniform(0.9, 1.05))
    return _jpeg(canvas, rng.randint(70, 85))
