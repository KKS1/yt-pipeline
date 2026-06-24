import os
import time
import json
import random
import re
from datetime import datetime
import subprocess
from google import genai
from google.genai import types

# ===================================================================== #
# 1. PARAMETERS, NARRATIVE ARRAY & SAFETY LIMITS                       #
# ===================================================================== #
DAILY_SAFETY_LIMIT = 490  
COUNTER_FILE = "gemini_usage_tracker.json"
output_dir = "output_images"
output_video_name = "english_vibes_lesson_master.mp4"
os.makedirs(output_dir, exist_ok=True)

prompts = [
    "Masterpiece 3D Pixar style. Emma (brown pony tail) and Liam (blonde) standing side-by-side in a sunny suburban backyard next to a barbecue grill.",
    "Masterpiece 3D Pixar style. Emma and Liam sitting at a wooden picnic table in the backyard, laughing and eating fresh burgers.",
    "Masterpiece 3D Pixar style. Close up on a golden retriever dog running across the green lawn of the suburban backyard chasing a red frisbee.",
    "Masterpiece 3D Pixar style. Emma and Liam sitting around a small backyard firepit at sunset, holding marshmallows on sticks. Warm cozy lighting."
]

image_paths_mapped = [os.path.join(output_dir, f"dynamic_scene_{i}.jpg") for i in range(1, len(prompts) + 1)]
client = genai.Client()

# FIX: Restricted pool to clean, non-distracting effects ideal for text-shadowing channels
TRANSITION_POOL = ["fade", "wipeleft", "wiperight", "hlslice"]

# ===================================================================== #
# 2. LOCAL TRACKER FUNCTIONS                                           #
# ===================================================================== #
def check_and_update_quota(increment=False):
    today = datetime.now().strftime("%Y-%m-%d")
    data = {"date": today, "count": 0}
    if os.path.exists(COUNTER_FILE):
        try:
            with open(COUNTER_FILE, "r") as f:
                loaded_data = json.load(f)
                if loaded_data.get("date") == today:
                    data = loaded_data
        except (json.JSONDecodeError, KeyError):
            pass
    if increment:
        data["count"] += 1
        with open(COUNTER_FILE, "w") as f:
            json.dump(data, f, indent=4)
    return data["count"]

# ===================================================================== #
# 3. GENERATION PHASE: DOWNLOAD PROGRESSIVE SEQUENCED IMAGES            #
# ===================================================================== #
current_daily_count = check_and_update_quota(increment=False)
print(f"📊 Free Tier Tracker: Current usage: {current_daily_count}/{DAILY_SAFETY_LIMIT} images.")

for i, (prompt, path) in enumerate(zip(prompts, image_paths_mapped), start=1):
    if not os.path.exists(path):
        current_daily_count = check_and_update_quota(increment=False)
        if current_daily_count >= DAILY_SAFETY_LIMIT:
            print(f"🛑 SAFETY HALT: Local cap reached. Skipping generation for Image {i}.")
            continue
            
        print(f"📡 Generating Image {i}/{len(prompts)} via Cost-Optimized Multimodal Pipeline...")
        try:
            response = client.models.generate_content(
                model='gemini-2.5-flash-image',
                contents=prompt,
                config=types.GenerateContentConfig(response_modalities=["IMAGE"])
            )
            
            image_written = False
            for part in response.candidates.content.parts:
                if part.inline_data is not None:
                    with open(path, "wb") as f:
                        f.write(part.inline_data.data)
                    new_count = check_and_update_quota(increment=True)
                    print(f"✅ Image {i} downloaded as '{os.path.basename(path)}'! (Daily usage: {new_count}/{DAILY_SAFETY_LIMIT})")
                    image_written = True
                    time.sleep(2)  
                    break
            if not image_written:
                print(f"❌ Failed to extract visual payload for Image {i}.")
                exit(1)
        except Exception as e:
            print(f"❌ Gemini image generation phase failed on Image {i}: {e}")
            exit(1)
    else:
        print(f"🔄 Image {i} already exists at '{os.path.basename(path)}'. Skipping API request.")

# ===================================================================== #
# 4. DISCOVERY & STABILIZED NATURAL SORTING LAYER                      #
# ===================================================================== #
SUPPORTED_EXTENSIONS = (".jpg", ".jpeg", ".png")
ordered_storyboard_tuples = []
pattern = re.compile(r"dynamic_scene_(\d+)")

if os.path.exists(output_dir):
    for filename in os.listdir(output_dir):
        if filename.lower().endswith(SUPPORTED_EXTENSIONS):
            match = pattern.search(filename)
            if match:
                scene_num = int(match.group(1))
                full_path = os.path.join(output_dir, filename)
                ordered_storyboard_tuples.append((scene_num, full_path))

ordered_storyboard_tuples.sort(key=lambda item: item[0])
image_paths = [path for _, path in ordered_storyboard_tuples]

if len(image_paths) == 0:
    print(f"❌ Aborted: No valid images found on disk.")
    exit(1)

# ===================================================================== #
# 5. DYNAMIC MULTI-INPUT TIMELINE STRATIFICATION ENGINE                #
# ===================================================================== #
print(f"Initiating sequential {len(image_paths)}-track video pipeline...")

duration = 10  
fade_duration = 1
fps = 24
total_frames = duration * fps  

input_flags = []
filter_elements = []

for idx, path in enumerate(image_paths):
    input_flags.extend(["-loop", "1", "-r", str(fps), "-t", str(duration), "-i", f'"{path}"'])
    
    # Subtly gentler Ken Burns zoom levels tailored for high readability focus
    if idx % 2 == 0:
        motion_filter = (
            f"[{idx}:v] scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(ih-ih)/2,"
            f"scale='1920*(1+0.04*n/{total_frames})':-1:eval=frame,crop=1920:1080:(iw-ow)/2:(ih-oh)/2,setsar=1[v_track_{idx}];"
        )
    else:
        motion_filter = (
            f"[{idx}:v] scale=2016:1134:force_original_aspect_ratio=decrease,pad=2016:1134:(ow-iw)/2:(ih-ih)/2,"
            f"scale='2016*(1-0.03*n/{total_frames})':-1:eval=frame,crop=1920:1080:'(iw-ow)/2':'(ih-oh)/2',setsar=1[v_track_{idx}];"
        )
    filter_elements.append(motion_filter)

current_offset = duration - fade_duration  

if len(image_paths) > 1:
    for idx in range(len(image_paths) - 1):
        chosen_transition = random.choice(TRANSITION_POOL)
        name_current = os.path.basename(image_paths[idx])
        name_next = os.path.basename(image_paths[idx+1])
        print(f"⛓️  Transitioning '{name_current}' ➔ '{name_next}' via language-safe effect: '{chosen_transition}'")
        
        if idx == 0:
            xfade_link = f"[v_track_0][v_track_1] xfade=transition={chosen_transition}:duration={fade_duration}:offset={current_offset}"
        else:
            xfade_link = f"[mix_{idx-1}][v_track_{idx+1}] xfade=transition={chosen_transition}:duration={fade_duration}:offset={current_offset}"
            
        if idx == len(image_paths) - 2:
            xfade_link += "[outv]"
        else:
            xfade_link += f"[mix_{idx}]; "
            
        filter_elements.append(xfade_link)
        current_offset += (duration - fade_duration)
    
    map_target = "[outv]"
else:
    filter_elements.append("[v_track_0] copy [outv]")
    map_target = "[outv]"

input_string = " ".join(input_flags)
filter_complex_string = " ".join(filter_elements)

ffmpeg_cmd = (
    f'ffmpeg -y {input_string} -filter_complex "{filter_complex_string}" -map "{map_target}" '
    f'-c:v h264_videotoolbox -pix_fmt yuv420p "{output_video_name}"'
)

try:
    print("\nCompiling language learning optimized timeline...")
    subprocess.run(ffmpeg_cmd, shell=True, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    total_len = (duration - fade_duration) * len(image_paths) + fade_duration if len(image_paths) > 1 else duration
    print(f"\n🎯 SUCCESS! Open '{output_video_name}' to see your smooth {total_len}-second educational clip.")
except subprocess.CalledProcessError as e:
    print(f"❌ FFmpeg execution failed:\n{e.stderr.decode()}")
