import json
import random
import requests
import os

GROQ_API_KEY = os.getenv("GROQ_API_KEY")

ENGLISH_TOPIC_POOL = [
    "Using Phrasal Verbs with 'Look'",
    "Ordering Food at a Restaurant",
    "Checking in at a Hotel",
    "Talking about the Weather and Seasons",
    "Job Interview Basics in English",
    "Small Talk at a Party",
    "Asking for and Giving Directions",
    "Discussing Hobbies and Interests",
    "Phrasal Verbs for Travel and Holidays",
    "Everyday Office Conversations",
    "Describing People and Personalities",
    "Making Apologies and Excuses",
    "Shopping and Asking for Prices",
    "Talking about Future Plans",
    "Common Idioms for Happiness and Sadness",
    "Discussing Favorite Movies and Books",
    "Making Plans for the Weekend",
    "Talking about Food and Cooking",
    "Giving Advice to a Friend",
    "Phrasal Verbs with 'Get'"
]

def call_groq_json(user_prompt):
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": [
            {
                "role": "system",
                "content": "You generate perfect JSON for educational English conversation podcasts.",
            },
            {
                "role": "user",
                "content": user_prompt,
            },
        ],
        "temperature": 0.7,
        "max_tokens": 7000,
        "response_format": {
            "type": "json_object"
        },
    }

    response = requests.post(url, headers=headers, json=payload, timeout=120)
    if response.status_code != 200:
        raise Exception(f"Groq API error {response.status_code}: {response.text}")

    data = response.json()
    raw = data["choices"][0]["message"]["content"]
    return json.loads(raw)

def generate_english_script(topic=None):
    if not topic:
        topic = random.choice(ENGLISH_TOPIC_POOL)

    print(f"\nSelected topic: {topic}")

    print("Generating Part 1 (Intro & Setup)...")
    prompt_1 = f"""
You are writing PART 1 (of 3) for a massive English conversation podcast script for the YouTube channel 'EnglishVibesHub'.
TOPIC: {topic}

CRITICAL RULES:
- Output ONLY valid JSON
- The `dialogue` array MUST contain around 50-60 turns.

STRUCTURE & CONTENT (PART 1):
1. **Intro**: MUST start by welcoming the audience to "EnglishVibesHub" and introducing the topic of the day.
2. **Setup**: Begin the deep dive discussion into the topic.
3. Use and carefully explain 3-4 phrasal verbs or idioms. The hosts MUST explain what they mean to the listeners with clear examples.

STYLE:
- Conversational, friendly, and natural.
- Hosts: Emma (energetic, helpful) and Liam (curious, friendly).
- Ensure back-and-forth banter is highly detailed. Avoid short 1-sentence replies; instead, each turn should be a few sentences long to build up the word count.

JSON SCHEMA:
{{
  "title": "string (engaging YouTube title for the episode)",
  "description": "string (video description)",
  "tags": ["string"],
  "dialogue": [
    {{
      "speaker": "Emma or Liam",
      "text": "string (the spoken text)"
    }}
  ]
}}
"""
    part1_data = call_groq_json(prompt_1)

    print("Generating Part 2 (Deep Dive & Stories)...")
    last_turn = part1_data["dialogue"][-1] if part1_data.get("dialogue") else {"speaker": "Emma", "text": "Let's continue."}
    prompt_2 = f"""
You are writing PART 2 (of 3) for a massive English conversation podcast script for the YouTube channel 'EnglishVibesHub'.
TOPIC: {topic}

The previous turn ended with {last_turn['speaker']} saying: "{last_turn['text']}"
Pick up the conversation naturally from here.

CRITICAL RULES:
- Output ONLY valid JSON
- The `dialogue` array MUST contain around 50-60 turns.

STRUCTURE & CONTENT (PART 2):
1. **Deep Dive**: Continue the extensive discussion of the topic.
2. **Stories & Roleplay**: The hosts must share long personal stories or do a mock roleplay related to the topic to extend the conversation naturally.
3. Use and carefully explain 4-5 additional phrasal verbs or idioms. The hosts MUST explain what they mean to the listeners with clear examples.

STYLE:
- Conversational, friendly, and natural.
- Hosts: Emma (energetic, helpful) and Liam (curious, friendly).
- Ensure back-and-forth banter is highly detailed. Avoid short 1-sentence replies.

JSON SCHEMA:
{{
  "dialogue": [
    {{
      "speaker": "Emma or Liam",
      "text": "string (the spoken text)"
    }}
  ]
}}
"""
    part2_data = call_groq_json(prompt_2)

    print("Generating Part 3 (Wrap-up & Outro)...")
    last_turn_2 = part2_data["dialogue"][-1] if part2_data.get("dialogue") else {"speaker": "Emma", "text": "Let's wrap up."}
    prompt_3 = f"""
You are writing PART 3 (of 3) for a massive English conversation podcast script for the YouTube channel 'EnglishVibesHub'.
TOPIC: {topic}

The previous turn ended with {last_turn_2['speaker']} saying: "{last_turn_2['text']}"
Pick up the conversation naturally from here.

CRITICAL RULES:
- Output ONLY valid JSON
- The `dialogue` array MUST contain around 40-50 turns.

STRUCTURE & CONTENT (PART 3):
1. **Wrap-up**: Share final thoughts, tips, or examples.
2. Use and carefully explain 3-4 final phrasal verbs or idioms. The hosts MUST explain what they mean to the listeners with clear examples.
3. **Outro**: MUST end by thanking the listeners, asking them to like, subscribe, and tune in for more learning and conversations on EnglishVibesHub.

STYLE:
- Conversational, friendly, and natural.
- Hosts: Emma (energetic, helpful) and Liam (curious, friendly).
- Ensure back-and-forth banter is highly detailed. Avoid short 1-sentence replies.

JSON SCHEMA:
{{
  "dialogue": [
    {{
      "speaker": "Emma or Liam",
      "text": "string (the spoken text)"
    }}
  ]
}}
"""
    part3_data = call_groq_json(prompt_3)

    # Combine all parts
    final_script = {
        "title": part1_data.get("title", f"English Conversation: {topic}"),
        "description": part1_data.get("description", f"Learn English with this detailed conversation about {topic}."),
        "tags": part1_data.get("tags", ["English", "Conversation", "Learning", "Phrasal Verbs"]),
        "dialogue": []
    }

    if "dialogue" in part1_data:
        final_script["dialogue"].extend(part1_data["dialogue"])
    if "dialogue" in part2_data:
        final_script["dialogue"].extend(part2_data["dialogue"])
    if "dialogue" in part3_data:
        final_script["dialogue"].extend(part3_data["dialogue"])

    return final_script
