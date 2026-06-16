import json
from pathlib import Path
from PIL import Image, ImageDraw

# Setup paths relative to script location
BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / "assets/characters/character_config.json"
OUTPUT_PATH = BASE_DIR / "output/layout_preview.png"

def main():
    if not CONFIG_PATH.exists():
        print(f"Error: Config file not found at {CONFIG_PATH}")
        return

    with open(CONFIG_PATH, "r") as f:
        config = json.load(f)

    canvas_cfg = config["canvas"]
    canvas_size = (canvas_cfg["width"], canvas_cfg["height"])

    # 1. Load Background
    bg_path = BASE_DIR / config.get("background", "")
    if bg_path.exists():
        frame = Image.open(bg_path).convert("RGBA").resize(canvas_size)
    else:
        print(f"Warning: Background {bg_path} not found. Using gray fallback.")
        frame = Image.new("RGBA", canvas_size, (50, 50, 50, 255))

    draw = ImageDraw.Draw(frame)

    # 2. Composite Characters
    for name, data in config.get("characters", {}).items():
        body_path = BASE_DIR / data["body"]
        pos = data["position"]
        mouth = data["mouth"]

        if body_path.exists():
            body_img = Image.open(body_path).convert("RGBA")
            body_img = body_img.resize((pos["width"], pos["height"]))
            frame.paste(body_img, (pos["x"], pos["y"]), body_img)

            # Calculate mouth position relative to character body
            # This matches the updated logic in dynamic_english_renderer.py
            abs_m_x = pos["x"] + mouth["x"]
            abs_m_y = pos["y"] + mouth["y"]

            # Draw a red box where lips will appear
            draw.rectangle(
                [abs_m_x, abs_m_y, abs_m_x + mouth["width"], abs_m_y + mouth["height"]],
                outline="red", width=5
            )
            print(f"✓ {name}: Placed. Lip sync target verified at ({abs_m_x}, {abs_m_y})")
        else:
            print(f"Error: Body image for {name} not found at {body_path}")

    # 3. Save and Show
    OUTPUT_PATH.parent.mkdir(exist_ok=True)
    frame.save(OUTPUT_PATH)
    frame.show()
    print(f"\nPreview generated: {OUTPUT_PATH}")

if __name__ == "__main__":
    main()