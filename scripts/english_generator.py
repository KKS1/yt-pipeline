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

def generate_english_script(topic=None):
    if not topic:
        topic = random.choice(ENGLISH_TOPIC_POOL)

    print(f"\nSelected topic: {topic}")

    prompt = f"""
You are writing a 15-minute simple English conversation podcast script for the YouTube channel 'EnglishVibesHub'.
The podcast is designed to help English learners improve their listening and speaking skills.

TOPIC:
{topic}

CRITICAL RULES:
- Output ONLY valid JSON
- No markdown
- No explanations
- No comments
- No code fences
- JSON must parse perfectly

STYLE:
- Conversational, friendly, and natural
- Simple English vocabulary but natural phrasing
- The hosts are Emma and Liam. Emma is energetic and helpful. Liam is curious and friendly.
- The conversation should include examples, clear explanations of any idioms or phrasal verbs used, and natural back-and-forth banter.
- Provide around 20-30 dialogue turns total to fill out a substantial podcast episode.

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

IMPORTANT:
Return ONLY JSON.
"""

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
                "content": prompt,
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
    script = json.loads(raw)
    return script
