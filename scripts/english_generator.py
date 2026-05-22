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
You are writing a MASSIVE, 2500+ word English conversation podcast script for the YouTube channel 'EnglishVibesHub'. 
This script MUST translate to 15-20 minutes of spoken audio. Do NOT generate a short script.

TOPIC:
{topic}

CRITICAL RULES:
- Output ONLY valid JSON
- No markdown
- No explanations
- No comments
- No code fences
- JSON must parse perfectly
- The `dialogue` array MUST contain at least 150 items.

STRUCTURE & CONTENT REQUIREMENTS:
1. **Intro**: Must start by welcoming the audience to "EnglishVibesHub" and introducing the topic of the day.
2. **Deep Dive**: Extensive discussion of the topic.
3. **Vocabulary & Phrasal Verbs**: Deliberately use AT LEAST 10 different relevant phrasal verbs and idioms. When used, the hosts MUST naturally explain what they mean to the listeners with clear examples.
4. **Stories & Roleplay**: The hosts must share long personal stories or do a mock roleplay related to the topic to extend the conversation naturally.
5. **Outro**: Must end by thanking the listeners, asking them to like, subscribe, and tune in for more learning and conversations.

STYLE:
- Conversational, friendly, and natural.
- Simple English vocabulary but natural phrasing.
- The hosts are Emma and Liam. Emma is energetic and helpful. Liam is curious and friendly.
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
