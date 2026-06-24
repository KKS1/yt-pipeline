import os
import time
import json
from datetime import datetime
import subprocess
from google import genai
from google.genai import types

# ===================================================================== #
# 1. PARAMETERS, CONFIGURATION & SAFETY LIMITS                        #
# ===================================================================== #
DAILY_SAFETY_LIMIT = 490  
COUNTER_FILE = "gemini_usage_tracker.json"
output_dir = "output_images"
os.makedirs(output_dir, exist_ok=True)

hd_prompt = (
    "Masterpiece 3D Pixar animation style. Widescreen landscape frame. "
    "A beautiful 25-year-old woman named Emma with brown hair in a neat ponytail, "
    "and a handsome 25-year-old man named Liam with short blonde hair. "
    "They are standing side-by-side in a sunny suburban backyard next to a smoking barbecue grill. "
    "Perfect human anatomy, symmetrical facial features, highly detailed, Disney character design, cinematic lighting."
)
landscape_image_path = os.path.join(output_dir, "base_widescreen_scene.jpg")

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
# 3. IMAGE PIPELINE PHASE WITH COUNTER VALIDATION                     #
# ===================================================================== #
current_daily_count = check_and_update_quota(increment=False)
print(f"📊 Free Tier Tracker: You have generated {current_daily_count}/{DAILY_SAFETY_LIMIT} images today.")

if not os.path.exists(landscape_image_path):
    if current_daily_count >= DAILY_SAFETY_LIMIT:
        print(f"🛑 SAFETY HALT: Daily local cap reached to protect your free tier status.")
        exit(0)
        
    target_model = 'gemini-2.5-flash-image'
    print(f"Connecting to Google AI Studio Free Pipeline via: {target_model}")
    
    try:
        client = genai.Client()
        response = client.models.generate_content(
            model=target_model,
            contents=hd_prompt,
            config=types.GenerateContentConfig(
                response_modalities=["IMAGE"],
            )
        )
        
        image_written = False
        for part in response.candidates.content.parts:
            if part.inline_data is not None:
                image_bytes = part.inline_data.data
                with open(landscape_image_path, "wb") as f:
                    f.write(image_bytes)
                
                new_count = check_and_update_quota(increment=True)
                print(f"✅ Image downloaded! New daily total: {new_count}/{DAILY_SAFETY_LIMIT}")
                image_written = True
                break
        
        if not image_written:
            print("❌ Response received, but no valid inline image payload was extracted.")
            exit(1)
            
    except Exception as e:
        print(f"❌ Gemini image generation phase failed: {e}")
        exit(1)
else:
    print("🔄 Base image already exists locally. Skipping API generation phase.")

# ===================================================================== #
# 4. MULTI-THREAD OPTIMIZED CINEMATIC VIDEO PIPELINE (INSTANT RENDER)   #
# ===================================================================== #
if os.path.exists(landscape_image_path):
    print("\nInitiating hardware-accelerated video pipeline...")
    output_video_name = "scene_1_gemini_master.mp4"
    duration = 10  
    fps = 24

    # Determine effect alternate behavior using current daily count number
    if current_daily_count % 2 == 0:
        print("🎬 Applying iMovie Style A: Slow Zoom Out + Gentle Right Pan")
        # FIX: Added ':eval=frame' so FFmpeg evaluates 'n' on every frame without crashing
        filter_graph = (
            "scale=2112:1188:force_original_aspect_ratio=decrease,pad=2112:1188:(ow-iw)/2:(ih-ih)/2,"
            "scale='2112*(1-0.05*n/120)':-1:eval=frame,crop=1920:1080:'(iw-ow)*(n/120)':'(ih-oh)/2',setsar=1"
        )
    else:
        print("🎬 Applying iMovie Style B: Cinematic Center Zoom In")
        # FIX: Added ':eval=frame' to enable frame-by-frame canvas recalculation
        filter_graph = (
            "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(ih-ih)/2,"
            "scale='1920*(1+0.06*n/120)':-1:eval=frame,crop=1920:1080:(iw-ow)/2:(ih-oh)/2,setsar=1"
        )

    # FIX: Switched to Apple Silicon hardware encoder 'h264_videotoolbox' for instant rendering
    ffmpeg_cmd = (
        f'ffmpeg -y -loop 1 -r {fps} -t {duration} -i "{landscape_image_path}" -vf "{filter_graph}" '
        f'-c:v h264_videotoolbox -pix_fmt yuv420p "{output_video_name}"'
    )

    try:
        print("Compiling distortion-free canvas adaptive video track...")
        subprocess.run(ffmpeg_cmd, shell=True, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        print(f"\n🎯 SUCCESS! Open '{output_video_name}' to see your smooth, iMovie-grade clip.")
    except subprocess.CalledProcessError as e:
        print(f"❌ FFmpeg execution failed: {e.stderr.decode()}")
else:
    print("❌ Base image file missing. Render stopped.")
