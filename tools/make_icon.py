"""Generate `app/cat.ico` (multi-resolution Windows icon).

Renders a small cat face onto a PDF page silhouette so the icon
visually combines "cat" with "document".  Drawn with PIL, no network.
"""

from __future__ import annotations

import os
from PIL import Image, ImageDraw


def draw_pdf_with_cat(size: int) -> Image.Image:
    """Square RGBA canvas containing a PDF page silhouette and a cat."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img, "RGBA")

    s = size
    # ----- PDF page silhouette (rounded rectangle with folded corner) -----
    page_color = (255, 240, 220, 255)
    edge_color = (40, 30, 20, 255)
    pad = int(s * 0.08)
    page = (pad, pad, s - pad, s - pad)
    # Body
    radius = int(s * 0.08)
    d.rounded_rectangle(page, radius=radius, fill=page_color, outline=edge_color, width=max(1, s // 96))
    # Folded corner (top-right triangle)
    fold = int(s * 0.18)
    d.polygon([
        (s - pad - fold, pad),
        (s - pad, pad + fold),
        (s - pad - fold, pad + fold),
    ], fill=(230, 215, 195, 255), outline=edge_color)

    # ----- Cat face occupying most of the page -----
    cx = s // 2
    cy = int(s * 0.55)
    head_r = int(s * 0.30)
    fur = (240, 150, 40, 255)        # orange tabby
    fur_dark = (200, 110, 20, 255)

    # Ears
    ear_left = [
        (cx - int(head_r * 0.95), cy - int(head_r * 0.3)),
        (cx - int(head_r * 0.55), cy - int(head_r * 1.25)),
        (cx - int(head_r * 0.10), cy - int(head_r * 0.4)),
    ]
    ear_right = [
        (cx + int(head_r * 0.10), cy - int(head_r * 0.4)),
        (cx + int(head_r * 0.55), cy - int(head_r * 1.25)),
        (cx + int(head_r * 0.95), cy - int(head_r * 0.3)),
    ]
    d.polygon(ear_left, fill=fur, outline=edge_color)
    d.polygon(ear_right, fill=fur, outline=edge_color)
    # Inner ear pink
    pink = (250, 180, 200, 255)
    d.polygon([
        (cx - int(head_r * 0.78), cy - int(head_r * 0.35)),
        (cx - int(head_r * 0.55), cy - int(head_r * 0.95)),
        (cx - int(head_r * 0.30), cy - int(head_r * 0.42)),
    ], fill=pink)
    d.polygon([
        (cx + int(head_r * 0.30), cy - int(head_r * 0.42)),
        (cx + int(head_r * 0.55), cy - int(head_r * 0.95)),
        (cx + int(head_r * 0.78), cy - int(head_r * 0.35)),
    ], fill=pink)

    # Head circle
    d.ellipse(
        (cx - head_r, cy - head_r, cx + head_r, cy + head_r),
        fill=fur, outline=edge_color, width=max(1, s // 96),
    )

    # Stripes (subtle)
    stripe = fur_dark
    sw = max(1, s // 80)
    d.line([(cx - head_r * 0.7, cy - head_r * 0.7),
            (cx - head_r * 0.4, cy - head_r * 0.55)], fill=stripe, width=sw)
    d.line([(cx + head_r * 0.7, cy - head_r * 0.7),
            (cx + head_r * 0.4, cy - head_r * 0.55)], fill=stripe, width=sw)
    d.line([(cx - head_r * 0.9, cy - head_r * 0.1),
            (cx - head_r * 0.6, cy - head_r * 0.0)], fill=stripe, width=sw)
    d.line([(cx + head_r * 0.9, cy - head_r * 0.1),
            (cx + head_r * 0.6, cy - head_r * 0.0)], fill=stripe, width=sw)

    # Eyes (sleepy / arc-shaped to look cute)
    eye_color = (30, 30, 30, 255)
    eye_y = cy - int(head_r * 0.05)
    eye_w = int(head_r * 0.22)
    eye_h = int(head_r * 0.18)
    d.ellipse((cx - int(head_r * 0.42) - eye_w, eye_y - eye_h,
               cx - int(head_r * 0.42) + eye_w, eye_y + eye_h),
              fill=(255, 255, 255, 255), outline=edge_color)
    d.ellipse((cx + int(head_r * 0.42) - eye_w, eye_y - eye_h,
               cx + int(head_r * 0.42) + eye_w, eye_y + eye_h),
              fill=(255, 255, 255, 255), outline=edge_color)
    pupil_r = max(2, int(eye_w * 0.55))
    d.ellipse((cx - int(head_r * 0.42) - pupil_r, eye_y - pupil_r,
               cx - int(head_r * 0.42) + pupil_r, eye_y + pupil_r), fill=eye_color)
    d.ellipse((cx + int(head_r * 0.42) - pupil_r, eye_y - pupil_r,
               cx + int(head_r * 0.42) + pupil_r, eye_y + pupil_r), fill=eye_color)
    # Eye highlights
    hl = max(1, pupil_r // 3)
    d.ellipse((cx - int(head_r * 0.42) - hl + 1, eye_y - hl - 1,
               cx - int(head_r * 0.42) + hl + 1, eye_y + hl - 1),
              fill=(255, 255, 255, 255))
    d.ellipse((cx + int(head_r * 0.42) - hl + 1, eye_y - hl - 1,
               cx + int(head_r * 0.42) + hl + 1, eye_y + hl - 1),
              fill=(255, 255, 255, 255))

    # Nose
    nose_color = (220, 110, 110, 255)
    d.polygon([
        (cx - int(head_r * 0.08), cy + int(head_r * 0.18)),
        (cx + int(head_r * 0.08), cy + int(head_r * 0.18)),
        (cx, cy + int(head_r * 0.30)),
    ], fill=nose_color, outline=edge_color)

    # Mouth
    mw = max(1, s // 96)
    d.line([(cx, cy + int(head_r * 0.30)),
            (cx, cy + int(head_r * 0.40))], fill=edge_color, width=mw)
    d.arc((cx - int(head_r * 0.20), cy + int(head_r * 0.30),
           cx, cy + int(head_r * 0.55)), 0, 180, fill=edge_color, width=mw)
    d.arc((cx, cy + int(head_r * 0.30),
           cx + int(head_r * 0.20), cy + int(head_r * 0.55)), 0, 180, fill=edge_color, width=mw)

    # Whiskers
    ww = max(1, s // 128)
    d.line([(cx - int(head_r * 0.30), cy + int(head_r * 0.30)),
            (cx - int(head_r * 0.95), cy + int(head_r * 0.20))], fill=edge_color, width=ww)
    d.line([(cx - int(head_r * 0.30), cy + int(head_r * 0.38)),
            (cx - int(head_r * 0.95), cy + int(head_r * 0.40))], fill=edge_color, width=ww)
    d.line([(cx + int(head_r * 0.30), cy + int(head_r * 0.30)),
            (cx + int(head_r * 0.95), cy + int(head_r * 0.20))], fill=edge_color, width=ww)
    d.line([(cx + int(head_r * 0.30), cy + int(head_r * 0.38)),
            (cx + int(head_r * 0.95), cy + int(head_r * 0.40))], fill=edge_color, width=ww)

    return img


def main() -> None:
    here = os.path.dirname(os.path.abspath(__file__))
    out_dir = os.path.join(here, "..", "app")
    os.makedirs(out_dir, exist_ok=True)

    big = draw_pdf_with_cat(256)
    ico_path = os.path.abspath(os.path.join(out_dir, "cat.ico"))
    big.save(
        ico_path,
        format="ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    png_path = os.path.abspath(os.path.join(out_dir, "cat.png"))
    big.save(png_path, format="PNG")
    print(f"Wrote {ico_path}")
    print(f"Wrote {png_path}")


if __name__ == "__main__":
    main()
