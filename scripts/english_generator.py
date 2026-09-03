import json
import os
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from groq_client import groq_chat_json, groq_part_cooldown

# Free tier TPM is 12k; three 7k-cap calls in a row exceed it. Lower cap + pause between parts.
ENGLISH_MAX_TOKENS = int(os.getenv("GROQ_ENGLISH_MAX_TOKENS", "4096"))

PUBLISHED_TOPICS_FILE = Path(__file__).resolve().parent / "english_published_topics.json"

PAUSE_CUE_RE = re.compile(r"^\s*\[(?:PAUSE|PAUSE\s+(\d+(?:\.\d+)?)\s*SECONDS?)\]\s*$", re.IGNORECASE)

ENGLISH_METADATA_RULES = """
METADATA RULES:
- Titles must be high-CTR, emotionally-driven, under 70 chars. Use ONE of these structures (rotate, don't repeat consecutively):
  A. Crisis hook: "I Said [X] and They Got OFFENDED"
  B. Urgency gap: "STOP Using [X] — Here's Why"
  C. Social proof: "Native Speakers NEVER Say [X]"
  D. Curiosity bomb: "The [X] Secret Nobody Teaches"
  E. Story cliffhanger: "Lost in [Situation] Because of [X]"
  F. Mistake shame: "You Sound RUDE When You Say [X]"
  G. Comparison shock: "[A] vs [B]: One Makes You Look Dumb"
  H. Personal failure: "I Embarrassed Myself With [X]"
  I. Challenge: "Only 10% Pass This [X] Test"
  J. Cultural warning: "Don't Say [X] in English (Trust Me)"
- FORBIDDEN WORDS: "practice", "learn", "master", "English lesson", "tutorial", "study" — these kill CTR
- Include chosen structure letter (A-J) as "title_structure" field. Selective ALL CAPS for 1-2 power words max.
- Descriptions: Front-load SEO line ("English listening practice for [topic]"), include "Natural English" and "Speak like a native" in first 2-3 lines. Use keyword variations.
- Include playlist CTA (📺 Watch the playlist here: {playlist_url}), comment CTA, subscribe CTA, and hashtags (max 5).
- Hashtags: #LearnEnglish #EnglishListeningPractice #<TopicRelated> #SpeakEnglishNaturally #EnglishVibesHub
- Use ONLY {playlist_url} placeholder (not actual URLs).
- Tags: high-intent SEO mixing broad English-learning + topic-specific terms. Pinned comments: specific question viewers can answer quickly.
- SPOKEN DIALOGUE: Never use forward slashes ('/') in spoken dialogue text — write out 'or' or separate options with commas (e.g., 'Option A or Option B', 'he or she', 'either or').
"""

PODCAST_METADATA_RULES = """
METADATA RULES (PODCAST — under 3 min clips):
- Titles under 70 chars, high-CTR, emotionally-driven. NEVER use "Episode X" or series numbering.
- Use ONE of these structures (rotate): A. Crisis hook B. Story cliffhanger C. Mistake-in-action D. Curiosity bomb E. Relatable pain F. Cultural shock G. Direct address H. Personal failure
- FORBIDDEN WORDS: "practice", "learn", "master", "English lesson", "tutorial", "study" — these kill CTR
- Include chosen letter as "title_structure". Selective ALL CAPS for 1-2 power words max.
- Descriptions: Front-load SEO ("English podcast: [topic]"), include "Natural English" and "Speak like a native".
- Include {playlist_url} placeholder, comment CTA, subscribe CTA, hashtags (max 5).
- Hashtags: #LearnEnglish #EnglishListeningPractice #<TopicRelated> #SpeakEnglishNaturally #EnglishVibesHub
"""

ENGLISH_STORYBOARD_STYLE_SUFFIX_LANDSCAPE = (
    "3D Pixar animation style, Disney character design, cinematic lighting, 16:9 aspect ratio."
)
ENGLISH_STORYBOARD_STYLE_SUFFIX_PORTRAIT = (
    "3D Pixar animation style, Disney character design, cinematic lighting, 9:16 aspect ratio."
)

_PLAYLIST_LINE_RE = re.compile(
    r"""
    ^\s*
    (?:[-*•▶️🎬📺🎧📚🔥✨]\s*)?
    (?:
        watch|see|view|check\s+out|listen\s+to|catch
    )\s+
    (?:
        the\s+|this\s+|our\s+
    )?
    (?:
        full\s+|complete\s+|entire\s+
    )?
    (?:
        playlist|series
    )
    (?:
        \s+here|\s+playlist
    )?
    \s*:?
    \s*
    (?:
        \{playlist_url\}|https?://\S+|\[[^\]]+\]
    )?
    \s*$
    """,
    re.IGNORECASE | re.VERBOSE,
)


_TOPIC_STOP_WORDS = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "need", "dare", "ought",
    "used", "to", "of", "in", "for", "on", "with", "at", "by", "from",
    "up", "about", "into", "through", "during", "before", "after",
    "and", "but", "or", "nor", "not", "so", "yet", "both", "either",
    "neither", "each", "every", "all", "any", "few", "more", "most",
    "other", "some", "such", "no", "only", "own", "same", "than",
    "too", "very", "just", "because", "as", "until", "while",
    "disaster", "nightmare", "story", "practice", "learn", "english",
})

# Map English-learning themes to high-value related hashtags
_THEME_HASHTAG_MAP = {
    "airport": ["#AirportEnglish", "#TravelEnglish"],
    "restaurant": ["#RestaurantEnglish", "#OrderingFood"],
    "hotel": ["#HotelEnglish", "#TravelEnglish"],
    "doctor": ["#DoctorEnglish", "#MedicalEnglish"],
    "hospital": ["#HospitalEnglish", "#MedicalEnglish"],
    "interview": ["#JobInterview", "#BusinessEnglish"],
    "meeting": ["#BusinessMeeting", "#BusinessEnglish"],
    "phone": ["#PhoneEnglish", "#PhoneCall"],
    "shopping": ["#ShoppingEnglish", "#RetailEnglish"],
    "bank": ["#BankEnglish", "#FinanceEnglish"],
    "classroom": ["#ClassroomEnglish", "#AcademicEnglish"],
    "workplace": ["#WorkplaceEnglish", "#BusinessEnglish"],
    "supermarket": ["#SupermarketEnglish", "#ShoppingEnglish"],
    "cafe": ["#CafeEnglish", "#OrderingFood"],
    "taxi": ["#TaxiEnglish", "#TravelEnglish"],
    "uber": ["#RideShareEnglish", "#TravelEnglish"],
    "gym": ["#GymEnglish", "#FitnessEnglish"],
    "gossip": ["#GossipEnglish", "#CasualConversation"],
    "argument": ["#ArgumentEnglish", "#ConflictResolution"],
    "apology": ["#ApologyEnglish", "#PoliteEnglish"],
    "complaint": ["#ComplaintEnglish", "#CustomerService"],
    "wedding": ["#WeddingEnglish", "#SocialEnglish"],
    "dating": ["#DatingEnglish", "#SocialEnglish"],
    "job": ["#JobEnglish", "#CareerEnglish"],
    "office": ["#OfficeEnglish", "#BusinessEnglish"],
    "weather": ["#WeatherEnglish", "#SmallTalk"],
    "food": ["#FoodEnglish", "#OrderingFood"],
    "travel": ["#TravelEnglish", "#AirportEnglish"],
    "money": ["#MoneyEnglish", "#FinanceEnglish"],
    "home": ["#HomeEnglish", "#DailyEnglish"],
    "family": ["#FamilyEnglish", "#DailyEnglish"],
    "friend": ["#FriendEnglish", "#CasualConversation"],
    "school": ["#SchoolEnglish", "#AcademicEnglish"],
    "car": ["#DrivingEnglish", "#TravelEnglish"],
    "bus": ["#BusEnglish", "#TravelEnglish"],
    "train": ["#TrainEnglish", "#TravelEnglish"],
    "mistake": ["#CommonMistakes", "#EnglishGrammar"],
    "greeting": ["#EnglishGreeting", "#DailyEnglish"],
    "slang": ["#EnglishSlang", "#CasualConversation"],
    "idiom": ["#EnglishIdioms", "#NaturalEnglish"],
    "idioms": ["#EnglishIdioms", "#NaturalEnglish"],
    "pronunciation": ["#EnglishPronunciation", "#SpeakEnglish"],
    "grammar": ["#EnglishGrammar", "#LearnEnglish"],
    "vocabulary": ["#EnglishVocabulary", "#SpeakEnglish"],
    "conversation": ["#EnglishConversation", "#SpeakEnglish"],
    "small talk": ["#SmallTalk", "#CasualConversation"],
    "polite": ["#PoliteEnglish", "#DailyEnglish"],
    "expression": ["#EnglishExpressions", "#NaturalEnglish"],
    "expressions": ["#EnglishExpressions", "#NaturalEnglish"],
    "phrase": ["#EnglishPhrases", "#SpeakEnglish"],
    "phrases": ["#EnglishPhrases", "#SpeakEnglish"],
    "saying": ["#EnglishSayings", "#NaturalEnglish"],
    "sayings": ["#EnglishSayings", "#NaturalEnglish"],
    "word": ["#EnglishVocabulary", "#DailyEnglish"],
    "reply": ["#EnglishReply", "#CasualConversation"],
    "response": ["#EnglishResponse", "#CasualConversation"],
    "question": ["#EnglishQuestions", "#SpeakEnglish"],
    "answer": ["#EnglishAnswers", "#SpeakEnglish"],
    "request": ["#EnglishRequest", "#PoliteEnglish"],
    "offer": ["#EnglishOffer", "#CasualConversation"],
    "refuse": ["#EnglishRefusal", "#PoliteEnglish"],
    "compliment": ["#EnglishCompliment", "#SocialEnglish"],
    "confusion": ["#EnglishConfusion", "#CommonMistakes"],
    "natural": ["#NaturalEnglish", "#SpeakEnglish"],
    "fluency": ["#EnglishFluency", "#SpeakEnglish"],
    "fluently": ["#EnglishFluency", "#SpeakEnglish"],
    "beginner": ["#EnglishForBeginners", "#LearnEnglish"],
    "advanced": ["#AdvancedEnglish", "#EnglishVocabulary"],
    "business": ["#BusinessEnglish", "#ProfessionalEnglish"],
    "email": ["#BusinessEmail", "#BusinessEnglish"],
    "resume": ["#ResumeEnglish", "#JobInterview"],
    "customer": ["#CustomerService", "#EnglishForWork"],
    "service": ["#CustomerService", "#EnglishForWork"],
    "negotiation": ["#NegotiationEnglish", "#BusinessEnglish"],
    "presentation": ["#PresentationEnglish", "#BusinessEnglish"],
    "casual": ["#CasualEnglish", "#CasualConversation"],
    "formal": ["#FormalEnglish", "#BusinessEnglish"],
    "informal": ["#InformalEnglish", "#CasualConversation"],
    "native": ["#NativeEnglish", "#NaturalEnglish"],
    "fluently": ["#SpeakFluently", "#EnglishFluency"],
    "accent": ["#EnglishAccent", "#Pronunciation"],
    "listening": ["#EnglishListening", "#EnglishPractice"],
    "speaking": ["#EnglishSpeaking", "#SpeakEnglish"],
    "reading": ["#EnglishReading", "#LearnEnglish"],
    "writing": ["#EnglishWriting", "#LearnEnglish"],
    "test": ["#EnglishTest", "#EnglishPractice"],
    "quiz": ["#EnglishQuiz", "#EnglishPractice"],
    "challenge": ["#EnglishChallenge", "#EnglishPractice"],
    "daily": ["#DailyEnglish", "#EverydayEnglish"],
    "everyday": ["#EverydayEnglish", "#DailyEnglish"],
    "real": ["#RealEnglish", "#NaturalEnglish"],
    "real life": ["#RealEnglish", "#EverydayEnglish"],
    "situation": ["#EnglishSituations", "#EverydayEnglish"],
    "context": ["#EnglishContext", "#NaturalEnglish"],
    "common": ["#CommonEnglish", "#EverydayEnglish"],
    "popular": ["#PopularEnglish", "#SpeakEnglish"],
    "useful": ["#UsefulEnglish", "#SpeakEnglish"],
    "important": ["#ImportantEnglish", "#SpeakEnglish"],
    "simple": ["#SimpleEnglish", "#EnglishForBeginners"],
    "easy": ["#EasyEnglish", "#EnglishForBeginners"],
    "hard": ["#DifficultEnglish", "#CommonMistakes"],
    "difficult": ["#DifficultEnglish", "#CommonMistakes"],
    "confusing": ["#ConfusingEnglish", "#CommonMistakes"],
    "wrong": ["#EnglishMistakes", "#CommonMistakes"],
    "correct": ["#CorrectEnglish", "#EnglishGrammar"],
    "better": ["#BetterEnglish", "#SpeakEnglish"],
    "improve": ["#ImproveEnglish", "#EnglishPractice"],
    "practice": ["#EnglishPractice", "#SpeakEnglish"],
    "learn": ["#LearnEnglish", "#EnglishPractice"],
    "teach": ["#TeachEnglish", "#LearnEnglish"],
    "understand": ["#UnderstandEnglish", "#EnglishListening"],
    "meaning": ["#EnglishMeaning", "#EnglishVocabulary"],
    "difference": ["#EnglishDifference", "#CommonMistakes"],
    "similar": ["#SimilarEnglish", "#CommonMistakes"],
    "instead": ["#EnglishInstead", "#CommonMistakes"],
    "say": ["#HowToSay", "#SpeakEnglish"],
    "speak": ["#SpeakEnglish", "#EnglishFluency"],
    "talk": ["#EnglishTalk", "#CasualConversation"],
    "chat": ["#EnglishChat", "#CasualConversation"],
    "text": ["#EnglishText", "#CasualConversation"],
    "social media": ["#SocialMediaEnglish", "#CasualConversation"],
    "internet": ["#InternetEnglish", "#CasualConversation"],
    "movie": ["#MovieEnglish", "#EnglishListening"],
    "music": ["#MusicEnglish", "#EnglishListening"],
    "song": ["#SongEnglish", "#EnglishListening"],
    "news": ["#NewsEnglish", "#EnglishListening"],
    "story": ["#EnglishStory", "#EnglishListening"],
    "book": ["#EnglishBook", "#EnglishReading"],
    "game": ["#GameEnglish", "#CasualConversation"],
    "sport": ["#SportEnglish", "#CasualConversation"],
    "shopping": ["#ShoppingEnglish", "#RetailEnglish"],
    "clothes": ["#ClothesEnglish", "#ShoppingEnglish"],
    "color": ["#ColorEnglish", "#DailyEnglish"],
    "color": ["#ColourEnglish", "#DailyEnglish"],
    "time": ["#TellingTime", "#DailyEnglish"],
    "date": ["#EnglishDate", "#DailyEnglish"],
    "number": ["#EnglishNumbers", "#DailyEnglish"],
    "count": ["#EnglishCounting", "#DailyEnglish"],
}


def _build_topic_hashtags(theme: str) -> str:
    """Extract 1-2 high-value topic hashtags from a theme string.

    Uses a known-theme lookup first, then falls back to extracting the
    most meaningful noun-like words from the theme.
    """
    if not theme:
        return ""
    theme_lower = theme.lower()

    # Check known-theme map for high-value related hashtags
    for keyword, tags in _THEME_HASHTAG_MAP.items():
        if keyword in theme_lower:
            return " ".join(tags)

    # Fallback: extract meaningful words from theme
    theme_clean = re.sub(r"[^\w\s]", "", theme_lower).strip()
    words = [
        w for w in theme_clean.split()
        if w not in _TOPIC_STOP_WORDS and len(w) > 2
    ]
    if not words:
        return ""
    # Use the longest word as primary topic hashtag (most likely the noun/topic)
    words_sorted = sorted(words, key=len, reverse=True)
    primary = words_sorted[0].capitalize()
    if len(words_sorted) >= 2 and words_sorted[1] != words_sorted[0]:
        return f"#English{primary} #English{words_sorted[1].capitalize()}"
    return f"#English{primary}"


def _strip_all_hashtags(text: str) -> str:
    """Remove all hashtags from a description, preserving other content lines."""
    hashtag_re = re.compile(r"#\w+")
    cleaned_lines = []
    for line in text.splitlines():
        if not line.strip():
            cleaned_lines.append("")
            continue
        if not hashtag_re.search(line):
            cleaned_lines.append(line)
            continue
        cleaned = hashtag_re.sub("", line).strip()
        cleaned = re.sub(r" {2,}", " ", cleaned)
        if cleaned:
            cleaned_lines.append(cleaned)
    return "\n".join(cleaned_lines)


def ensure_english_vibes_hashtags(description: str, theme: str = "", *, is_shorts: bool = False, is_slow_english: bool = False) -> str:
    """Ensure hashtags appear at the end of the description — capped at 5 max for YouTube SEO.
    
    For longform/podcast: #LearnEnglish #EnglishListeningPractice #<TopicRelated> #SpeakEnglishNaturally #EnglishVibesHub
    For slow-english: #EnglishForBeginners #SlowEnglish #<TopicRelated> #SpeakEnglishNaturally #EnglishVibesHub
    For shorts/quiz: Uses existing strategy (unchanged)
    """
    text = str(description or "").strip()
    
    # Shorts/quiz keep existing strategy
    if is_shorts:
        if not text:
            return "#Shorts #EnglishQuiz #LearnEnglish"
        cleaned_text = _strip_all_hashtags(text)
        core_tags = ["#Shorts", "#EnglishQuiz", "#LearnEnglish"]
        topic_tags_list = _build_topic_hashtags(theme).split() if _build_topic_hashtags(theme) else []
        tags = core_tags + topic_tags_list[:2]
        seen = set()
        unique_tags = []
        for t in tags:
            if t not in seen:
                seen.add(t)
                unique_tags.append(t)
        hashtag_line = " ".join(unique_tags[:5])
        hashtag_line = re.sub(r" {2,}", " ", hashtag_line)
        cleaned_text = cleaned_text.strip()
        if cleaned_text and not cleaned_text.endswith("\n"):
            cleaned_text += "\n\n"
        cleaned_text += hashtag_line
        cleaned_text = re.sub(r"\n{3,}", "\n\n", cleaned_text)
        return cleaned_text.strip()
    
    # Slow-english: special beginner-focused strategy
    if is_slow_english:
        if not text:
            return "#EnglishForBeginners #SlowEnglish #SpeakEnglishNaturally #EnglishVibesHub"
        cleaned_text = _strip_all_hashtags(text)
        core_tags = ["#EnglishForBeginners", "#SlowEnglish", "#SpeakEnglishNaturally", "#EnglishVibesHub"]
        topic_tags_list = _build_topic_hashtags(theme).split() if _build_topic_hashtags(theme) else []
        tags = core_tags + topic_tags_list[:1]
        seen = set()
        unique_tags = []
        for t in tags:
            if t not in seen:
                seen.add(t)
                unique_tags.append(t)
        hashtag_line = " ".join(unique_tags[:5])
        hashtag_line = re.sub(r" {2,}", " ", hashtag_line)
        cleaned_text = cleaned_text.strip()
        if cleaned_text and not cleaned_text.endswith("\n"):
            cleaned_text += "\n\n"
        cleaned_text += hashtag_line
        cleaned_text = re.sub(r"\n{3,}", "\n\n", cleaned_text)
        return cleaned_text.strip()
    
    # Longform/podcast: new 5-tag strategy
    if not text:
        return "#LearnEnglish #EnglishListeningPractice #SpeakEnglishNaturally #EnglishVibesHub"
    
    cleaned_text = _strip_all_hashtags(text)
    
    # Build hashtag line — exactly 5 tags for longform/podcast
    core_tags = ["#LearnEnglish", "#EnglishListeningPractice", "#SpeakEnglishNaturally", "#EnglishVibesHub"]
    topic_tags_list = _build_topic_hashtags(theme).split() if _build_topic_hashtags(theme) else []
    
    # Assemble: core (4) + topic (1) = 5
    tags = core_tags + topic_tags_list[:1]
    # Deduplicate while preserving order
    seen = set()
    unique_tags = []
    for t in tags:
        if t not in seen:
            seen.add(t)
            unique_tags.append(t)
    hashtag_line = " ".join(unique_tags[:5])
    hashtag_line = re.sub(r" {2,}", " ", hashtag_line)
    
    # Append hashtags at the very end with blank line separator
    cleaned_text = cleaned_text.strip()
    if cleaned_text and not cleaned_text.endswith("\n"):
        cleaned_text += "\n\n"
    cleaned_text += hashtag_line
    
    # Clean up excessive blank lines
    cleaned_text = re.sub(r"\n{3,}", "\n\n", cleaned_text)
    return cleaned_text.strip()


def update_pinned_comment_with_channel_cta(script_data: dict) -> dict:
    """
    Append the channel CTA to the pinned comment for shorts and quiz formats.
    This encourages viewers to find the full playlists on the channel home page.
    """
    if not script_data:
        return script_data

    existing_comment = script_data.get("pinned_comment", "")
    channel_cta = "Find the full 'English Quiz' & 'English MasterClass Series' playlists and much more on our channel home page @EnglishVibesHub-S6W!"

    if existing_comment and channel_cta not in existing_comment:
        script_data["pinned_comment"] = f"{existing_comment}\n\n{channel_cta}"
    elif not existing_comment:
        script_data["pinned_comment"] = channel_cta

    return script_data


def validate_organic_english_script(raw_input):
    """
    Validation engine tailored for the Organic Multi-Character English Prompt layout.
    Accepts raw JSON text string or a Python dictionary object.
    """
    if isinstance(raw_input, dict):
        script_data = raw_input
    else:
        try:
            script_data = json.loads(raw_input)
        except Exception as e:
            print(f"❌ Structural Failure: Output is not valid parseable JSON. Error: {e}")
            return raw_input, False

    dialogue = script_data.get("dialogue", [])
    turn_count = len(dialogue)

    # 1. VALIDATE TURN BOUNDARIES (Rule: 28+ turns for organic format - doubled for longer videos)
    if turn_count < 28:
        print(f"❌ Retention Failure: Script has {turn_count} turns. Must be at least 28.")
        return script_data, False

    # Track structural validation targets
    has_pause = False
    has_narrator = False
    has_actors = False

    for turn in dialogue:
        turn_num = turn.get("turn_number")
        speaker = turn.get("speaker")
        text = turn.get("text", "")

        # Check for speaker representation
        if speaker == "Narrator":
            has_narrator = True
            # Narrator shouldn't slip into first person text accidentally
            if text.startswith("I am ") or " my " in text.lower():
                print(f"⚠️ Warning: Narrator might have slipped into first-person at turn {turn_num}")

        if speaker in ["Emma", "Liam", "Guest"]:
            has_actors = True
            # 2. ENFORCE CHARACTER PERSPECTIVE: Catch third-person character slip-ups
            if text.startswith("He ran") or text.startswith("She said"):
                print(f"❌ Perspective Failure: Character {speaker} is speaking in third-person at turn {turn_num}.")
                return script_data, False

            # 3. ENFORCE CHARACTER RETENTION WALL: Stop meta-talk leaking into actors
            if "phrasal verb" in text.lower() or "expression means" in text.lower():
                print(f"❌ Persona Failure: Actor {speaker} broke character to explain a lesson at turn {turn_num}.")
                return script_data, False

        # 4. CAPTURE THE SHIFTING PAUSE MARKER
        PAUSE_PATTERN = re.compile(r'^\s*\[PAUSE\s+(\d+(?:\.\d+)?)\s*SECONDS?\]\s*$', re.IGNORECASE)
        if PAUSE_PATTERN.match(text.strip()):
            has_pause = True
        elif "[PAUSE" in text.upper():
            # Pause marker found but not on its own line - this is invalid
            print(f"❌ Pause Format Failure: Pause marker is mixed with other text at turn {turn_num}. Pause must be on its own turn.")
            return script_data, False

    # Final logic balance check
    if not has_narrator or not has_actors:
        print("❌ Cast Failure: Script is missing either the Narrator or the Protag actors.")
        return script_data, False

    if not has_pause:
        print("❌ Interactive Failure: Script did not include the [PAUSE 3 SECONDS] token.")
        return script_data, False

    print(f"✅ Organic Script Verification Passed! Verified {turn_count} turns successfully.")
    return script_data, True


def validate_podcast_script(raw_input):
    """
    Validation engine for English podcast format (character-driven, no Narrator).
    Accepts raw JSON text string or a Python dictionary object.
    """
    if isinstance(raw_input, dict):
        script_data = raw_input
    else:
        try:
            script_data = json.loads(raw_input)
        except Exception as e:
            print(f"❌ Structural Failure: Output is not valid parseable JSON. Error: {e}")
            return raw_input, False

    dialogue = script_data.get("dialogue", [])
    turn_count = len(dialogue)

    # 1. VALIDATE TURN BOUNDARIES (Podcast format — 40+ turns for full 7-stage structure - doubled for longer videos)
    if turn_count < 40 or turn_count > 130:
        print(f"❌ Retention Failure: Script has {turn_count} turns. Must be between 40 and 130.")
        return script_data, False

    # 2. VALIDATE THEME FIELD (optional — fall back to title if missing)
    theme = script_data.get("theme", "")
    if not theme:
        # Auto-derive from title if available
        title = script_data.get("title", "")
        if title:
            script_data["theme"] = " ".join(title.split()[:5])
            print(f"  [info] Theme missing — derived from title: '{script_data['theme']}'")
        else:
            script_data["theme"] = "English Podcast"
            print("  [info] Theme missing — using fallback 'English Podcast'")
    elif len(theme.split()) < 2 or len(theme.split()) > 5:
        print(f"⚠️ Theme Warning: Theme should be 2-5 words. Got: '{theme}' (continuing anyway)")

    # 3. VALIDATE 5-PART PODCAST STRUCTURE
    # Check that dialogue contains the expected sections in reasonable order
    first_speaker = dialogue[0].get("speaker", "") if dialogue else ""
    last_speaker = dialogue[-1].get("speaker", "") if dialogue else ""
    
    # Story Hook should start with Caller (in media res), not hosts
    if first_speaker not in ["Caller", "Caller_Male", "StoryActor1", "StoryActor2"]:
        print(f"⚠️ Structure Warning: Podcast should start with Story Hook (Caller/StoryActor), not {first_speaker}. Current start may not be in media res.")
    
    # Should have hosts (Emma/Liam) present
    host_turns = [t for t in dialogue if t.get("speaker") in ["Emma", "Liam"]]
    if not host_turns:
        print("❌ Structure Failure: No host (Emma/Liam) turns found in dialogue.")
        return script_data, False
    
    # Should have Caller present
    caller_turns = [t for t in dialogue if t.get("speaker") in ("Caller", "Caller_Male")]
    if not caller_turns:
        print("❌ Structure Failure: No Caller turns found in dialogue.")
        return script_data, False

    # Track structural validation targets
    has_pause = False
    has_hosts = False
    has_caller = False
    has_story_actors = False
    has_narrator = False

    # Track speaker roles to detect role switching
    speaker_roles = {}

    for turn in dialogue:
        turn_num = turn.get("turn_number")
        speaker = turn.get("speaker")
        text = turn.get("text", "")

        # Track what roles each speaker takes
        if speaker not in speaker_roles:
            speaker_roles[speaker] = set()
        
        # Check for Narrator presence (not allowed in podcast format)
        if speaker == "Narrator":
            has_narrator = True
            print(f"❌ Persona Failure: Narrator is not allowed in podcast format at turn {turn_num}. Use Caller instead.")
            return script_data, False
        
        if speaker == "Emma" or speaker == "Liam":
            has_hosts = True
            speaker_roles[speaker].add("host")
            # Hosts should not break into story dialogue
            if "I was at" in text or "I said to" in text:
                print(f"❌ Persona Failure: Host {speaker} slipped into first-person story dialogue at turn {turn_num}.")
                return script_data, False

        if speaker in ("Caller", "Caller_Male"):
            has_caller = True
            speaker_roles[speaker].add("caller")
            # Caller may use first person ("I was confused when...") or third person ("my friend said...")
            # Both are valid with the 3rd-person framing change

        if speaker in ["StoryActor1", "StoryActor2", "StoryActor1_Female", "StoryActor2_Male", "StoryActor1_AltMale", "StoryActor2_AltFemale"]:
            has_story_actors = True
            # Normalize to base role for tracking
            base_role = "StoryActor1" if speaker.startswith("StoryActor1") else "StoryActor2"
            speaker_roles[speaker].add("story_actor")
            # StoryActors speak as themselves in direct dialogue — check for narration patterns
            narration_patterns = [
                r"(?i)\bI\s+(raised|leaned|whispered|nodded|replied|said|shook|smiled|frowned|looked|turned|walked|stepped|tried|explained|answered|clarified|told)\b",
                r"(?i)\b(he|she)\s+(raised|leaned|whispered|nodded|replied|said|shook|smiled|frowned|looked|turned|walked|stepped|tried|explained|answered|clarified|told)\b",
                r"(?i)\b(we|they)\s+(had\s+to|tried\s+to|were)\s+(clarify|explain|tell|call)\b",
                r"(?i)\b(he|she)\s+heard\s+(me|us)\s+(say|tell|explain)\b",
                r"(?i)\ball\s+because\s+of\b",
                r"(?i)\bfrom\s+the\s+doorway\b",
                r"(?i)\blooking\s+uncomfortable\b",
            ]
            for pattern in narration_patterns:
                if re.search(pattern, text):
                    print(f"⚠️ Narration Warning: StoryActor {speaker} appears to be narrating instead of speaking directly at turn {turn_num}: '{text[:80]}...'")
                    break

        # Check for third-person slip-ups (invalid for character-driven format)
        if speaker in ["Caller", "Caller_Male", "StoryActor1", "StoryActor2", "StoryActor1_Female", "StoryActor2_Male", "StoryActor1_AltMale", "StoryActor2_AltFemale"]:
            if text.startswith("He ran") or text.startswith("She said") or text.startswith("They went"):
                print(f"❌ Perspective Failure: Character {speaker} is speaking in third-person at turn {turn_num}.")
                return script_data, False

        # 4. CAPTURE THE SHIFTING PAUSE MARKER
        PAUSE_PATTERN = re.compile(r'^\s*\[PAUSE\s+(\d+(?:\.\d+)?)\s*SECONDS?\]\s*$', re.IGNORECASE)
        if PAUSE_PATTERN.match(text.strip()):
            has_pause = True
        elif "[PAUSE" in text.upper():
            # Pause marker found but not on its own line - this is invalid
            print(f"❌ Pause Format Failure: Pause marker is mixed with other text at turn {turn_num}. Pause must be on its own turn.")
            return script_data, False

    # Final logic balance check
    if not has_hosts:
        print("❌ Cast Failure: Script is missing podcast hosts (Emma/Liam).")
        return script_data, False

    if not has_caller:
        print("❌ Cast Failure: Script is missing Caller character.")
        return script_data, False

    if not has_pause:
        print("❌ Interactive Failure: Script did not include the [PAUSE 3 SECONDS] token.")
        return script_data, False

    # Check for role switching (same speaker taking multiple incompatible roles)
    for speaker, roles in speaker_roles.items():
        if len(roles) > 1:
            print(f"❌ Role Consistency Failure: Speaker {speaker} is switching between roles: {roles}")
            return script_data, False

    # 4. VALIDATE 7-STAGE STRUCTURE: Caller Story Setup + Back-to-Studio checks
    # After the last StoryActor turn, there should be at least one Caller turn
    # before host analysis begins (the "linger confusion" reflection beat).
    last_story_actor_idx = -1
    first_story_actor_idx = -1
    first_host_idx = -1
    for i, t in enumerate(dialogue):
        sp = t.get("speaker", "")
        if first_host_idx == -1 and sp in ["Emma", "Liam"]:
            first_host_idx = i
        if sp.startswith("StoryActor"):
            if first_story_actor_idx == -1:
                first_story_actor_idx = i
            last_story_actor_idx = i
    
    # Check that Caller does NOT appear within the story section (between first and last StoryActor)
    if first_story_actor_idx >= 0 and last_story_actor_idx > first_story_actor_idx:
        caller_in_story = [
            t for t in dialogue[first_story_actor_idx:last_story_actor_idx + 1]
            if t.get("speaker") in ("Caller", "Caller_Male")
        ]
        if caller_in_story:
            print(f"⚠️ Structure Warning: Caller appears {len(caller_in_story)} time(s) within the story section (between StoryActor turns). Caller should only appear in hook (Stage 1), caller setup (Stage 3), and back-to-studio (Stage 5), not in Stage 4.")
    
    # Check for Caller Story Setup: Caller should have turns between first host turn and first StoryActor
    if first_host_idx >= 0 and first_story_actor_idx > first_host_idx:
        caller_setup_turns = [
            t for t in dialogue[first_host_idx:first_story_actor_idx]
            if t.get("speaker") in ("Caller", "Caller_Male")
        ]
        if not caller_setup_turns:
            print("⚠️ Structure Warning: No Caller turns found between studio intro and story. Expected a 'Caller Story Setup' beat where Caller briefly tells hosts what happened before the flashback.")
    
    if last_story_actor_idx >= 0 and last_story_actor_idx < len(dialogue) - 1:
        # Check if there's a Caller turn after the last StoryActor turn
        has_caller_reflection = any(
            t.get("speaker") in ("Caller", "Caller_Male")
            for t in dialogue[last_story_actor_idx + 1:]
        )
        if not has_caller_reflection:
            print("⚠️ Structure Warning: No Caller reflection turn found after the story ends. Expected a 'back to studio' beat where Caller expresses lingering confusion.")

    # 5. VALIDATE VISUAL PROMPT CONTEXT ALIGNMENT
    scenes = script_data.get("scenes", [])
    if scenes:
        # Extract story content from dialogue
        story_text = " ".join([t.get("text", "") for t in dialogue if t.get("speaker") in ["Caller", "Caller_Male", "StoryActor1", "StoryActor2"]]).lower()
        
        # Generic location keywords that shouldn't appear unless story actually involves them
        generic_locations = [
            "marketplace", "subway", "train station", "train platform",
            "bus stop", "airport terminal", "high school", "school hallway",
            "classroom", "coffee shop", "shopping mall", "gym",
            "lockers", "hallway", "cafeteria",
        ]
        
        for scene in scenes:
            visual_prompt = scene.get("visual_prompt", "").lower()
            image_filename = scene.get("image_filename", "")
            
            # Skip host scenes
            if image_filename == "podcast_host.png":
                continue
            
            # Check if visual prompt uses generic locations not in story
            for loc in generic_locations:
                if loc in visual_prompt and loc not in story_text:
                    print(f"⚠️ Visual Prompt Warning: Scene {scene.get('scene_id')} uses generic location '{loc}' not found in story content. Visual prompt: {visual_prompt[:100]}")
                    # Don't fail validation, just warn

    print(f"✅ Podcast Script Verification Passed! Verified {turn_count} turns successfully.")
    return script_data, True


def ensure_english_seo_opener(description: str, theme: str = "", *, format: str = "longform") -> str:
    """Ensure first line uses high-intent SEO opener with 🎯 icon, customized with theme/topic.

    Args:
        format: One of "longform", "shorts", "quiz", or "podcast" — controls the opener phrasing.
    """
    text = str(description or "").strip()
    theme_clean = str(theme or "").strip()

    # Build format-specific opener with proper keyword front-loading
    if format == "shorts":
        if theme_clean:
            seo_line = f"🎯 Learn natural English in 30 seconds: {theme_clean}. Master expressions to speak like a native!"
        else:
            seo_line = "🎯 Learn natural English in 30 seconds: practical expressions you can use today. Speak like a native!"
    elif format == "quiz":
        if theme_clean:
            seo_line = f"🎯 English quiz — {theme_clean}. Master natural English for real conversations and speak like a native!"
        else:
            seo_line = "🎯 English quiz — test your vocabulary. Master natural English for real conversations and speak like a native!"
    elif format == "podcast":
        if theme_clean:
            seo_line = f"🎯 English podcast — {theme_clean}. Listen, learn, and speak like a native!"
        else:
            seo_line = "🎯 English podcast — learn natural English through real conversations. Listen, learn, and speak like a native!"
    else:  # longform (default)
        if theme_clean:
            seo_line = f"🎯 English listening practice: {theme_clean}. Master natural English for real conversations and speak like a native!"
        else:
            seo_line = "🎯 English listening practice: learn practical English expressions. Master natural English for real conversations and speak like a native!"
    
    if not text:
        return seo_line
    
    lines = text.splitlines()
    
    # Remove leading hashtag lines (they'll be re-added at the end)
    while lines and lines[0].strip().startswith("#"):
        lines.pop(0)
    
    if not lines:
        return seo_line
    
    opener = lines[0].lower()
    
    # Check if opener already has proper SEO keywords
    required_keywords = ["english listening practice", "english speaking practice", "english quiz", "learn english", "slow english", "easy english"]
    has_proper_opener = any(keyword in opener for keyword in required_keywords)
    
    if has_proper_opener:
        # If opener exists but lacks theme, update it
        if theme_clean and theme_clean.lower() not in text.lower():
            candidate_lines = [seo_line] + (lines[1:] if len(lines) > 1 else [])
            # Deduplicate lines (case-insensitive)
            seen = set()
            deduped = []
            for ln in candidate_lines:
                key = ln.strip().lower()
                if not key:
                    deduped.append(ln)
                elif key not in seen:
                    seen.add(key)
                    deduped.append(ln)
            return "\n".join(deduped)
        return "\n".join(lines)
    
    # Add SEO opener at the beginning
    rest = "\n".join(lines)
    return seo_line + "\n\n" + rest


def build_scene_timeline(scenes: list, per_turn_times: list) -> str:
    """Build a formatted timeline block from scene turn ranges and Kokoro audio timings."""
    if not scenes or not per_turn_times:
        return "📑 Timeline:\n0:00 - Start"

    def fmt_time(seconds: float) -> str:
        seconds = max(0, int(seconds))
        return f"{seconds // 60}:{seconds % 60:02d}"

    lines = ["📑 Timeline:"]
    for scene in scenes:
        start_turn = int(scene.get("start_turn", 0))
        end_turn = int(scene.get("end_turn", start_turn))
        start_turn = max(0, min(start_turn, len(per_turn_times) - 1))
        end_turn = max(start_turn, min(end_turn, len(per_turn_times) - 1))
        start_sec = per_turn_times[start_turn][0]
        label = scene.get("scene_label") or scene.get("image_filename", f"Scene {scene.get('scene_id', '?')}")
        label = re.sub(r"^scene_\d+_", "", str(label).replace(".jpg", "").replace(".png", "").replace("_", " ").title())
        lines.append(f"{fmt_time(start_sec)} - {label}")
    return "\n".join(lines)


def inject_scene_timeline(description: str, timeline_block: str) -> str:
    """Replace {scene_timeline} placeholder or upgrade an existing timeline section."""
    text = str(description or "").strip()
    if "{scene_timeline}" in text:
        return text.replace("{scene_timeline}", timeline_block)
    if re.search(r"📑\s*Timeline:", text, re.IGNORECASE):
        return re.sub(
            r"📑\s*Timeline:.*?(?=\n\n|\Z)",
            timeline_block,
            text,
            count=1,
            flags=re.DOTALL | re.IGNORECASE,
        )
    if re.search(r"\bTimeline:\b", text, re.IGNORECASE):
        return re.sub(
            r"Timeline:.*?(?=\n\n|\Z)",
            timeline_block.replace("📑 Timeline:", "Timeline:"),
            text,
            count=1,
            flags=re.DOTALL | re.IGNORECASE,
        )
    # Insert after comment block if present, else after opener
    comment_match = re.search(r"💬[^\n]+\n?", text)
    if comment_match:
        insert_at = comment_match.end()
        return text[:insert_at].rstrip() + "\n\n" + timeline_block + "\n\n" + text[insert_at:].lstrip()
    lines = text.split("\n\n", 1)
    if len(lines) == 2:
        return lines[0] + "\n\n" + timeline_block + "\n\n" + lines[1]
    return text + "\n\n" + timeline_block


def _integrate_fragments(description: str) -> str:
    """Integrate orphaned fragments into the SEO opener line instead of removing them.
    
    Fragments like 'tips for airport security' are useful content that should be
    integrated into the description rather than deleted.
    """
    text = str(description or "").strip()
    lines = text.splitlines()
    filtered_lines = []
    fragments = []
    
    # Pattern for lines that are valid section markers or structured content
    section_marker_pattern = re.compile(
        r'^(?:🎯|📺|💬|🔔|📑|#|Subscribe|Watch|Comment|Timeline|About)',
        re.IGNORECASE
    )
    
    for line in lines:
        line_stripped = line.strip()
        if not line_stripped:
            filtered_lines.append(line)
            continue
        
        # Keep lines with section markers, hashtags, or URLs
        if (section_marker_pattern.match(line_stripped) or 
            line_stripped.startswith('#') or 
            'http' in line_stripped.lower() or
            '{playlist_url}' in line_stripped):
            filtered_lines.append(line)
            continue
        
        # Check if this is an orphaned fragment: line without structure that appears
        # to be broken content (no emoji, no URL, not a hashtag, no section marker)
        # and starts with lowercase (suggesting it's a continuation without context)
        if (not section_marker_pattern.search(line_stripped) and
            line_stripped[0].islower()):
            # Check if it's a fragment: short line OR starts with common fragment words
            fragment_starters = ['tips', 'and', 'or', 'but', 'so', 'also', 'plus', 'then']
            if (len(line_stripped) < 60 or 
                any(line_stripped.lower().startswith(word) for word in fragment_starters)):
                # This is a fragment - collect it for integration
                fragments.append(line_stripped.rstrip('.!?'))
                continue
        
        filtered_lines.append(line)
    
    # If we have fragments and an SEO opener, integrate them naturally
    if fragments and filtered_lines and filtered_lines[0].startswith('🎯'):
        opener = filtered_lines[0]
        # Remove trailing punctuation from fragments for cleaner integration
        cleaned_fragments = [f.rstrip('.!?') for f in fragments]
        
        if cleaned_fragments:
            # Find the theme/topic part in the opener (after "Story:" or similar)
            if 'Story:' in opener:
                # Insert fragments after "Story:" with natural connector
                story_idx = opener.find('Story:')
                if story_idx != -1:
                    after_story = opener[story_idx + 6:].strip()
                    
                    # Build natural fragment text with appropriate connectors
                    fragment_parts = []
                    for i, frag in enumerate(cleaned_fragments):
                        frag_lower = frag.lower()
                        if frag_lower.startswith('tips'):
                            fragment_parts.append('with ' + frag)
                        elif frag_lower.startswith('and'):
                            # Remove "and" prefix and join with previous part
                            if fragment_parts:
                                fragment_parts[-1] += ' and ' + frag[3:].strip()
                            else:
                                fragment_parts.append(frag[3:].strip())
                        else:
                            fragment_parts.append(frag)
                    
                    fragment_text = ' '.join(fragment_parts)
                    # Add space before fragment text for proper spacing
                    if fragment_text and not fragment_text.startswith(' '):
                        fragment_text = ' ' + fragment_text
                    # Reconstruct opener with proper spacing
                    opener = opener[:story_idx + 6] + fragment_text + ' - ' + after_story
                    filtered_lines[0] = opener
    
    result = "\n".join(filtered_lines)
    result = re.sub(r'\n{3,}', '\n\n', result)
    return result.strip()


def _cleanup_sentence_fragments(text: str) -> str:
    """Remove incomplete sentence fragments left after phrase deduplication.
    
    Fragments are sentences that:
    - Don't end with proper punctuation (.!?)
    - Start with lowercase (continuation fragments)
    - Are very short and lack verb structure
    - End with dangling infinitives/prepositions (e.g., "to", "for", "and")
    - Contain structured markers (emoji, URLs) but no ending punctuation (mashed content)
    """
    # First, insert period before structured markers mashed against text without punctuation
    # e.g., "fragment 📺 Watch" -> "fragment. 📺 Watch"
    text = re.sub(r'([a-z])\s+([🎯📺💬🔔📑#])', r'\1. \2', text)
    text = re.sub(r'([a-z])\s+(https?://)', r'\1. \2', text)
    text = re.sub(r'([a-z])\s+({playlist_url})', r'\1. \2', text)
    
    # Split into sentences - handle punctuation followed by whitespace OR emoji/structured markers
    sentences = re.split(r'(?<=[.!?])(?=\s|[🎯📺💬🔔📑#])', text)
    cleaned = []
    
    for sent in sentences:
        sent = sent.strip()
        if not sent:
            continue
        
        # Keep structured lines (emoji headers, hashtags, URLs, sections, playlist URLs)
        is_structured = bool(re.match(r'^[🎯📺💬🔔📑#]|https?://', sent) or '{playlist_url}' in sent)
        if is_structured:
            cleaned.append(sent)
            continue
        
        # Check if this sentence contains structured content but lacks ending punctuation
        has_structured_marker = bool(re.search(r'[🎯📺💬🔔📑#]|https?://|{playlist_url}', sent))
        ends_with_punct = bool(re.search(r'[.!?]$', sent))
        starts_lower = sent[0].islower() if sent else False
        has_verb = bool(re.search(r'\b(is|are|has|have|do|did|will|can|learn|master|improve|speak|practice|watch|subscribe)\b', sent, re.I))
        
        # Check for dangling infinitives/prepositions at end (e.g., "to", "for", "and")
        ends_with_dangling = bool(re.search(r'\b(to|for|and|or|but|so|with|in|on|at)\s*[.!?]?$', sent, re.I))
        
        # Skip fragments
        if (not ends_with_punct or 
            (starts_lower and len(sent) < 80) or
            (len(sent) < 20 and not has_verb) or
            (has_structured_marker and not ends_with_punct) or
            ends_with_dangling):
            continue
            
        cleaned.append(sent)
    
    return ' '.join(cleaned)


def remove_duplicate_phrases(description: str) -> str:
    """Remove duplicate occurrences of key phrases and entire lines from descriptions."""
    text = str(description or "").strip()
    
    # First, integrate orphaned fragments into the SEO opener
    text = _integrate_fragments(text)
    
    # Preserve existing structured sections (comment, subscribe, playlist) by not normalizing them
    # Only normalize the content that appears to be mashed together
    
    # List of phrases that should appear only once (but be careful not to remove theme/topic)
    phrases_to_dedup = [
        "speak like a native",
        "natural english",
        "master natural english",
        "improve your english skills",
        "real-life scenarios",
        "english listening practice",
        "english speaking practice",
        "for real conversations",
        "learn hidden meanings",
    ]
    
    for phrase in phrases_to_dedup:
        # Case-insensitive search for duplicates
        pattern = re.compile(re.escape(phrase), re.IGNORECASE)
        matches = pattern.findall(text)
        
        if len(matches) > 1:
            # Keep first occurrence, remove subsequent ones
            def replace_func(match):
                nonlocal count
                count += 1
                return match.group(0) if count == 1 else ""
            
            count = 0
            text = pattern.sub(replace_func, text)

    # Clean up sentence fragments left after phrase deduplication
    text = _cleanup_sentence_fragments(text)
    
    # Clean up fragmented phrases left after removal (but preserve theme/topic)
    text = re.sub(r'🎯\s+via\s+Story:[^!]*!', '', text, flags=re.IGNORECASE)  # Remove fragmented opener remnants
    text = re.sub(r'Master\s+and\s+!', '', text)  # Remove fragmented phrases
    text = re.sub(r'🎯\s+-\s+[^.!?]*\.?\s*🎯', '', text)  # Remove fragmented emoji sections
    text = re.sub(r':\s+[^.!?]*\s+Learn\s+hidden\s+meanings', '', text)  # Remove fragmented idiom quiz text
    text = re.sub(r'🎯\s+-\s+[^.!?]*\.', '', text)  # Remove standalone fragmented emoji lines
    text = re.sub(r',\s*!\s*', ', ', text)  # Clean up ", !" fragments
    text = re.sub(r'\s+!\s*', ' ', text)  # Clean up standalone "!" with spaces
    text = re.sub(r',\s*,\s*', ', ', text)  # Clean up double commas
    text = re.sub(r',\s*[a-z]+\s+to\s+in\s+[a-z]+\s+situations!', '', text, flags=re.IGNORECASE)  # Clean up specific fragment pattern
    
    # Remove duplicate playlist URLs (keep only one, preferably the placeholder)
    text = re.sub(r'📺\s+Watch\s+the\s+playlist\s+here:\s*https?://[^\s]+', '', text, flags=re.IGNORECASE)
    
    # Remove duplicate lines (case-insensitive, ignoring leading/trailing whitespace)
    lines = text.splitlines()
    seen_lines = {}
    unique_lines = []
    
    for line in lines:
        line_stripped = line.strip().lower()
        if not line_stripped:
            unique_lines.append(line)
            continue
        if line_stripped not in seen_lines:
            seen_lines[line_stripped] = True
            unique_lines.append(line)
    
    text = "\n".join(unique_lines)
    
    # Clean up extra whitespace from replacements (preserve newlines, only collapse multiple spaces within lines)
    text = re.sub(r'  +', ' ', text)  # Collapse multiple spaces but preserve newlines
    text = re.sub(r'\n\s*\n\s*\n', '\n\n', text)
    return text.strip()


# Canonical section order for YouTube descriptions (top to bottom).
# Each entry is a regex that matches the start of a section line.
_SECTION_ORDER = [
    ("seo", re.compile(r"^🎯")),
    ("about", re.compile(r"^📑\s*About")),
    ("playlist", re.compile(r"^📺\s*Watch\s+the\s+playlist", re.IGNORECASE)),
    ("comment", re.compile(r"^💬\s*Comment", re.IGNORECASE)),
    ("subscribe", re.compile(r"^🔔\s*Subscribe", re.IGNORECASE)),
    ("timeline", re.compile(r"^📑\s*Timeline", re.IGNORECASE)),
]


def normalize_description_spacing(text: str) -> str:
    """Ensure exactly one blank line between every section in a description.

    Also splits lines that contain multiple section markers (e.g., 💬 and 🔔
    on the same line from LLM output) into separate lines.
    """
    if not text or not text.strip():
        return text

    # Split lines that have multiple section markers mashed together
    # e.g. "💬 Comment below: X 🔔 Subscribe to Y" → two lines
    section_emoji_re = re.compile(r'(\s)([🎯📺💬🔔📑])\s')
    lines = text.splitlines()
    expanded: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            expanded.append("")
            continue
        # Find split points where a section emoji appears mid-line (not at start)
        # First, strip leading emoji to avoid false match at line start
        leading_match = re.match(r'^([🎯📺💬🔔📑])\s*', stripped)
        if leading_match:
            rest = stripped[leading_match.end():]
        else:
            rest = stripped
        parts = section_emoji_re.split(rest)
        if len(parts) > 1:
            # parts alternates: [text, space, emoji, text, space, emoji, ...]
            # Reconstruct lines
            first_text = parts[0].rstrip()
            if leading_match:
                first_line = f"{leading_match.group(1)} {first_text}".strip()
            else:
                first_line = first_text
            if first_line:
                expanded.append(first_line)
            i = 1
            while i < len(parts):
                _space = parts[i]      # whitespace
                emoji = parts[i + 1]   # emoji
                text_part = parts[i + 2].rstrip() if i + 2 < len(parts) else ""
                new_line = f"{emoji} {text_part}".strip()
                if new_line:
                    expanded.append(new_line)
                i += 3
        else:
            expanded.append(stripped)

    # Collapse consecutive blank lines to a single marker
    normalized: list[str] = []
    for line in expanded:
        if not line.strip():
            if normalized and normalized[-1] == "":
                continue
            normalized.append("")
        else:
            normalized.append(line.strip())

    # Ensure blank line between consecutive section markers
    _section_re = re.compile(r"^[🎯📺💬🔔📑#]")
    final: list[str] = []
    for i, line in enumerate(normalized):
        if i > 0 and _section_re.match(line) and _section_re.match(normalized[i - 1]):
            # Both current and previous are section markers — insert blank line
            if final and final[-1] != "":
                final.append("")
        final.append(line)

    # Remove leading/trailing blank lines
    while final and final[0] == "":
        final.pop(0)
    while final and final[-1] == "":
        final.pop()

    result = "\n".join(final)
    # Ensure exactly two newlines (one blank line) between sections
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result


def ensure_description_section_order(text: str) -> str:
    """Reorder description sections into the canonical YouTube SEO order.

    Sections not matching any known pattern are kept in place relative to
    the section they follow. Hashtags are always moved to the very end.
    """
    if not text or not text.strip():
        return text

    lines = text.splitlines()

    # Separate hashtag lines from the rest
    hashtag_lines = [l for l in lines if l.strip().startswith("#")]
    non_hashtag_lines = [l for l in lines if not l.strip().startswith("#")]

    # Group non-hashtag lines into sections.  A "section" starts when we
    # encounter a line matching one of the _SECTION_ORDER patterns.
    sections: list[tuple[str, list[str]]] = []  # (key, lines)
    current_key = "_preamble"
    current_lines: list[str] = []

    for line in non_hashtag_lines:
        stripped = line.strip()
        matched_key = None
        for key, pattern in _SECTION_ORDER:
            if pattern.search(stripped):
                matched_key = key
                break
        if matched_key and matched_key != current_key:
            # Start a new section
            if current_lines:
                sections.append((current_key, current_lines))
            current_key = matched_key
            current_lines = [line]
        else:
            current_lines.append(line)
    if current_lines:
        sections.append((current_key, current_lines))

    # Rebuild in canonical order, keeping unknown sections after the
    # section they most naturally follow.
    seen_keys: set[str] = set()
    ordered_sections: list[list[str]] = []

    for key, _ in _SECTION_ORDER:
        for sec_key, sec_lines in sections:
            if sec_key == key and sec_key not in seen_keys:
                ordered_sections.append(sec_lines)
                seen_keys.add(sec_key)
                break

    # Append any sections that didn't match a known key (in original order)
    for sec_key, sec_lines in sections:
        if sec_key not in seen_keys:
            ordered_sections.append(sec_lines)
            seen_keys.add(sec_key)

    # Reassemble: join sections with blank-line separators, then append hashtags
    result_parts: list[str] = []
    for sec_lines in ordered_sections:
        # Strip trailing blank lines from each section before joining
        while sec_lines and sec_lines[-1].strip() == "":
            sec_lines.pop()
        result_parts.append("\n".join(sec_lines))

    result = "\n\n".join(result_parts)

    # Append hashtags at the end
    if hashtag_lines:
        result = result.rstrip() + "\n\n" + "\n".join(hashtag_lines)

    # Final spacing normalization
    result = normalize_description_spacing(result)
    return result


def finalize_english_description(
    description: str,
    *,
    include_timeline: bool = False,
    is_quiz: bool = False,
    is_shorts: bool = False,
    is_slow_english: bool = False,
    format: str = "longform",
    theme: str = "",
) -> str:
    """Apply all English description post-processors in optimal order.

    Args:
        format: One of "longform", "shorts", or "quiz" — controls SEO opener phrasing.
        is_shorts: When True, includes #Shorts in the hashtag set.
        is_slow_english: When True, uses beginner-focused hashtag strategy.
    """
    # Extract existing structured content to preserve it
    existing_comment = None
    comment_match = re.search(r'💬\s*Comment\s+below:[^#🔔]+', description, re.IGNORECASE)
    if comment_match:
        existing_comment = comment_match.group(0).strip()
    
    # Processing order: fragment cleanup → dedup → SEO opener → timeline removal → CTAs → About section → hashtags → ordering → spacing
    text = remove_duplicate_phrases(description)  # Includes fragment cleanup
    text = ensure_english_seo_opener(text, theme=theme, format=format)
    
    if not include_timeline:
        text = remove_timeline_from_shorts(text)
    text = ensure_english_description_cta(text, include_timeline=include_timeline)
    
    if is_quiz:
        # Add About This Lesson section for quiz videos (inserts after SEO opener, before CTAs)
        text = ensure_english_quiz_about_section(text, theme=theme)
        # Place hashtags at end with SEO ordering
        text = ensure_english_quiz_shorts_hashtags(text, theme=theme)
    else:
        # Add About section: quiz-style for shorts, longform-style for longform
        if is_shorts:
            text = ensure_english_quiz_about_section(text, theme=theme)
        else:
            text = ensure_english_longform_about_section(text, theme=theme)
        text = ensure_english_vibes_hashtags(text, theme=theme, is_shorts=is_shorts, is_slow_english=is_slow_english)

    # Enforce canonical section order (playlist before comment before subscribe, etc.)
    text = ensure_description_section_order(text)
    # Final spacing normalization
    text = normalize_description_spacing(text)

    # Final safety net: re-check that core CTAs are present (downstream processors
    # can accidentally drop them, e.g. when _cleanup_sentence_fragments collapses
    # newlines and remove_timeline_from_shorts eats past the comment/subscribe).
    text = ensure_english_description_cta(text, include_timeline=include_timeline)

    # Restore LLM-specific comment if it was captured earlier
    if existing_comment:
        text = re.sub(
            r'💬\s*Comment\s+below:\s*Which\s+phrase\s+will\s+you\s+practice\s+today\?',
            existing_comment,
            text,
            flags=re.IGNORECASE
        )
        # Re-enforce order after replacement
        text = ensure_description_section_order(text)
        text = normalize_description_spacing(text)

    return text


def ensure_english_description_cta(description: str, *, include_timeline: bool = False) -> str:
    """Guarantee core YouTube metadata CTAs even if the model skips them with proper spacing."""
    text = str(description or "").strip()
    
    # First, remove any existing subscribe lines without bell icon (to re-add in correct position)
    text = re.sub(r'(?<!🔔\s)Subscribe\s+to\s+EnglishVibesHub[^\n]*', '', text, flags=re.IGNORECASE)
    
    additions = []

    # Order: playlist → comment → subscribe → timeline (timeline only for long-form)
    # Add playlist if missing (will be positioned after opener)
    if "{playlist_url}" not in text and not re.search(r"playlist", text, re.IGNORECASE):
        additions.append("📺 Watch the playlist here: {playlist_url}")
    
    # Only add generic comment if no comment section exists at all
    if not re.search(r"💬\s*comment", text, re.IGNORECASE):
        additions.append("💬 Comment below: Which phrase will you practice today?")
    
    # Add subscribe with bell icon if missing (comes before timeline)
    if not re.search(r"🔔\s*Subscribe", text, re.IGNORECASE):
        additions.append("\n\n🔔 Subscribe to EnglishVibesHub for more English listening, speaking, and vocabulary practice.")
    
    # Add timeline only for long-form videos (not shorts)
    if include_timeline and "{scene_timeline}" not in text and not re.search(
        r"\b(?:timeline|chapters?)\b", text, re.IGNORECASE
    ):
        additions.append("📑 Timeline:\n{scene_timeline}")

    if additions:
        # If text starts with SEO opener, insert additions after it
        if text.startswith("🎯"):
            first_blank = text.find("\n\n")
            if first_blank != -1:
                text = text[:first_blank] + "\n\n" + "\n\n".join(additions) + text[first_blank:]
            else:
                text = text + "\n\n" + "\n\n".join(additions)
        else:
            text = (text + "\n\n" if text else "") + "\n\n".join(additions)
    
    # Ensure proper spacing - no more than 2 consecutive blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def remove_timeline_from_shorts(description: str) -> str:
    """Remove timeline-like content from shorts descriptions (should not have timestamps)."""
    text = str(description or "").strip()
    
    # Remove entire timeline section including header with multiple patterns
    # Match "📑 Timeline:" or "Timeline:" followed by timestamp lines
    text = re.sub(
        r"📑\s*Timeline:.*?(?=\n\n|\Z)",
        "",
        text,
        flags=re.DOTALL | re.IGNORECASE
    )
    text = re.sub(
        r"\bTimeline:.*?(?=\n\n|\Z)",
        "",
        text,
        flags=re.DOTALL | re.IGNORECASE
    )
    
    # Also remove any remaining timestamp lines (in case they're standalone)
    lines = text.splitlines()
    filtered_lines = []
    for line in lines:
        line_stripped = line.strip()
        # Match patterns like "0:00 - Label", "1:23 - Label", or "0:00 Label"
        if re.match(r"^\s*\d+:\d{2}\s*-\s*", line_stripped):
            continue
        # Also match timestamps without dash separator
        if re.match(r"^\s*\d+:\d{2}\s+[A-Z]", line_stripped):
            continue
        filtered_lines.append(line)
    
    # Clean up extra blank lines after timeline removal
    result = "\n".join(filtered_lines)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


def ensure_english_quiz_shorts_hashtags(description: str, theme: str = "") -> str:
    """Place quiz Shorts hashtags at the END — capped at 5 max for YouTube SEO."""
    text = str(description or "").strip()
    if not text:
        return "#Shorts #EnglishQuiz #LearnEnglish"

    cleaned_text = _strip_all_hashtags(text)

    # Build hashtag line — cap at 5 total
    core_tags = ["#Shorts", "#EnglishQuiz", "#LearnEnglish"]
    topic_tags_list = _build_topic_hashtags(theme).split() if _build_topic_hashtags(theme) else []
    
    # Assemble: core (3) + topic (0-2) = 3-5
    tags = core_tags + topic_tags_list[:2]
    hashtag_line = " ".join(tags[:5])
    hashtag_line = re.sub(r" {2,}", " ", hashtag_line)

    # Append hashtags at the very end with blank line separator
    cleaned_text = cleaned_text.strip()
    if cleaned_text and not cleaned_text.endswith("\n"):
        cleaned_text += "\n\n"
    cleaned_text += hashtag_line

    # Clean up excessive blank lines
    cleaned_text = re.sub(r"\n{3,}", "\n\n", cleaned_text)
    return cleaned_text.strip()


def ensure_english_quiz_about_section(description: str, theme: str = "") -> str:
    """Add 'About This Lesson' section for quiz videos with AI-generated explanation, inserted immediately after SEO opener."""
    text = str(description or "").strip()
    if not text:
        return text
    
    # First, remove any existing About This Lesson sections to avoid duplicates
    text = re.sub(
        r"📑\s*About\s+This\s+Lesson:.*?(?=\n\n|\Z)",
        "",
        text,
        flags=re.DOTALL | re.IGNORECASE
    )
    
    # Extract idiom/theme for the explanation
    theme_clean = str(theme or "").strip()
    if not theme_clean:
        # Try to extract from description
        theme_match = re.search(r"idiom\s*[:\-]\s*([^.]+)", text, re.IGNORECASE)
        if theme_match:
            theme_clean = theme_match.group(1).strip()
    
    if not theme_clean:
        return text
    
    # Generate AI explanation for the idiom/theme
    try:
        prompt = f"""Generate a brief, engaging explanation (2-3 sentences) for an English learning quiz about: "{theme_clean}".
        
Format the response as a single paragraph starting with "What does the [term] mean?" and explaining the meaning in simple, everyday English context. End with "Test your vocabulary skills with your quick quiz!"
        
Return ONLY the explanation text, no other content."""
        
        explanation = call_groq_json(prompt)
        explanation_text = explanation.get("explanation", explanation.get("text", ""))
        
        if not explanation_text:
            # Fallback to generic explanation
            explanation_text = f'What does "{theme_clean}" mean? In everyday English conversation, this term has specific meaning. Test your vocabulary skills with your quick quiz!'
    except Exception as e:
        print(f"  [warn] AI explanation generation failed: {e}")
        # Fallback to generic explanation
        explanation_text = f'What does "{theme_clean}" mean? In everyday English conversation, this term has specific meaning. Test your vocabulary skills with your quick quiz!'
    
    # Build the About This Lesson section
    about_section = f"📑 About This Lesson:\n{explanation_text}"
    
    # Insert immediately after SEO opener (line starting with 🎯), before any CTAs
    lines = text.splitlines()
    if lines and lines[0].strip().startswith("🎯"):
        # Find the first CTA line (playlist, comment, subscribe, timeline)
        first_cta_idx = None
        cta_prefixes = ["📺", "💬", "🔔", "📑 Timeline"]
        for i, line in enumerate(lines[1:], start=1):
            if any(line.strip().startswith(prefix) for prefix in cta_prefixes):
                first_cta_idx = i
                break
        
        if first_cta_idx is not None:
            # Insert About section between SEO opener and first CTA
            result = "\n".join(lines[:first_cta_idx]) + "\n\n" + about_section + "\n\n" + "\n".join(lines[first_cta_idx:])
        else:
            # No CTAs found, insert after SEO opener
            result = lines[0] + "\n\n" + about_section
            if len(lines) > 1:
                result += "\n\n" + "\n".join(lines[1:])
    else:
        # If no SEO opener found, append at beginning
        result = about_section
        if text:
            result += "\n\n" + text
    
    # Clean up spacing
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


def ensure_english_longform_about_section(description: str, theme: str = "") -> str:
    """Add 'About this video' section for longform English videos with AI-generated explanation."""
    text = str(description or "").strip()
    if not text:
        return text
    
    # First, remove any existing About sections to avoid duplicates
    text = re.sub(
        r"📑\s*About\s+This\s+(?:Video|Lesson):.*?(?=\n\n|\Z)",
        "",
        text,
        flags=re.DOTALL | re.IGNORECASE
    )
    
    # Extract theme for the explanation
    theme_clean = str(theme or "").strip()
    if not theme_clean:
        return text
    
    # Generate AI explanation for the topic
    try:
        prompt = f"""Generate a brief, engaging explanation (2-3 sentences) for an English learning video about: "{theme_clean}".
        
Explain what the viewer will learn about this topic in simple, everyday English. Focus on why this topic matters for English learners and what they'll take away from watching.

Return ONLY the explanation text, no other content."""
        
        explanation = call_groq_json(prompt)
        explanation_text = explanation.get("explanation", explanation.get("text", ""))
        
        if not explanation_text:
            explanation_text = f"In this lesson, we explore the English expression \"{theme_clean}\" — a common phrase used in everyday conversations. Watch along to understand how native speakers use it and improve your natural English!"
    except Exception as e:
        print(f"  [warn] AI explanation generation failed: {e}")
        explanation_text = f"In this lesson, we explore the English expression \"{theme_clean}\" — a common phrase used in everyday conversations. Watch along to understand how native speakers use it and improve your natural English!"
    
    # Build the About this video section
    about_section = f"📑 About this video:\n{explanation_text}"
    
    # Insert immediately after SEO opener (line starting with 🎯), before any CTAs
    lines = text.splitlines()
    if lines and lines[0].strip().startswith("🎯"):
        # Find the first CTA line (playlist, comment, subscribe, timeline)
        first_cta_idx = None
        cta_prefixes = ["📺", "💬", "🔔", "📑 Timeline"]
        for i, line in enumerate(lines[1:], start=1):
            if any(line.strip().startswith(prefix) for prefix in cta_prefixes):
                first_cta_idx = i
                break
        
        if first_cta_idx is not None:
            # Insert About section between SEO opener and first CTA
            result = "\n".join(lines[:first_cta_idx]) + "\n\n" + about_section + "\n\n" + "\n".join(lines[first_cta_idx:])
        else:
            # No CTAs found, insert after SEO opener
            result = lines[0] + "\n\n" + about_section
            if len(lines) > 1:
                result += "\n\n" + "\n".join(lines[1:])
    else:
        # If no SEO opener found, append at beginning
        result = about_section
        if text:
            result += "\n\n" + text
    
    # Clean up spacing
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


def _normalize_dialogue_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


def _speaker_name(line: dict) -> str:
    return str(line.get("speaker") or line.get("character") or "").strip()


def flatten_dialogue(dialogue_list: list) -> list:
    """Recursively flattens nested lists or dictionaries containing dialogue keys."""
    if not dialogue_list:
        return []
    flat = []
    for item in dialogue_list:
        if isinstance(item, dict):
            if "dialogue" in item and isinstance(item["dialogue"], list):
                flat.extend(flatten_dialogue(item["dialogue"]))
            elif "dialogue_list" in item and isinstance(item["dialogue_list"], list):
                flat.extend(flatten_dialogue(item["dialogue_list"]))
            else:
                flat.append(item)
        elif isinstance(item, list):
            flat.extend(flatten_dialogue(item))
        else:
            flat.append(item)
    return flat


def align_scenes_to_turns(scenes: list, dialogue: list) -> list:
    """Attach start_turn/end_turn to each scene, prioritizing direct indices if present."""
    if not scenes or not dialogue:
        return scenes

    # Standardize image filenames to .png extension strictly
    for scene in scenes:
        if isinstance(scene, dict) and "image_filename" in scene and scene["image_filename"]:
            base, _ = os.path.splitext(scene["image_filename"])
            scene["image_filename"] = base + ".png"

    dialogue = flatten_dialogue(dialogue)
    num_turns = len(dialogue)

    # Check if all scenes have direct start_turn and end_turn indices
    has_indices = all("start_turn" in s and "end_turn" in s for s in scenes)
    if has_indices:
        aligned = []
        for scene in scenes:
            scene = dict(scene)
            # Remove repeated dialogues from scene to avoid duplication in JSON
            scene.pop("dialogues", None)
            scene.pop("dialogue_list", None)
            try:
                start = max(0, min(int(scene["start_turn"]), num_turns - 1))
                end = max(start, min(int(scene["end_turn"]), num_turns - 1))
            except (ValueError, TypeError):
                start = 0
                end = 0
            scene["start_turn"] = start
            scene["end_turn"] = end
            aligned.append(scene)

        # Validate scene coverage without redistributing turns
        # Respect AI-generated scene boundaries based on dialogue meaning
        if aligned:
            print(f"  [scene_align] Total dialogue turns: {num_turns}, scenes: {len(aligned)}")
            
            # Ensure first scene starts at turn 0
            if aligned[0]["start_turn"] != 0:
                print(f"  [warn] First scene starts at turn {aligned[0]['start_turn']}, forcing to 0")
                aligned[0]["start_turn"] = 0
            
            # Ensure last scene ends at final turn
            if aligned[-1]["end_turn"] != num_turns - 1:
                print(f"  [warn] Last scene ends at turn {aligned[-1]['end_turn']}, forcing to {num_turns - 1}")
                aligned[-1]["end_turn"] = num_turns - 1
            
            # Check for gaps or overlaps in scene coverage
            for i in range(len(aligned) - 1):
                current_end = aligned[i]["end_turn"]
                next_start = aligned[i + 1]["start_turn"]
                if next_start > current_end + 1:
                    print(f"  [warn] Gap between scene {i+1} (ends {current_end}) and scene {i+2} (starts {next_start})")
                elif next_start <= current_end:
                    print(f"  [warn] Overlap between scene {i+1} (ends {current_end}) and scene {i+2} (starts {next_start})")
            
            # Log final scene alignment for verification
            print(f"  [scene_align] Scene coverage:")
            for i, scene in enumerate(aligned):
                print(f"    Scene {i+1} ({scene.get('scene_label', '?')}): turns {scene['start_turn']}-{scene['end_turn']}")

        return aligned

    # Legacy fallback: sequential dialogue matching based on dialogues list
    turn_idx = 0
    aligned = []
    for scene in scenes:
        scene = dict(scene)
        dialogues = scene.get("dialogues") or scene.get("dialogue_list") or []
        if not dialogues:
            aligned.append(scene)
            continue

        start_turn = turn_idx
        for d_line in dialogues:
            if turn_idx >= len(dialogue):
                print(f"  [warn] Scene {scene.get('scene_id')}: ran out of dialogue turns at index {turn_idx}")
                break
            expected_text = _normalize_dialogue_text(d_line.get("text", ""))
            actual_text = _normalize_dialogue_text(dialogue[turn_idx].get("text", ""))
            expected_speaker = _speaker_name(d_line).lower()
            actual_speaker = _speaker_name(dialogue[turn_idx]).lower()
            if expected_text and expected_text != actual_text:
                print(
                    f"  [warn] Scene {scene.get('scene_id')} turn {turn_idx}: "
                    f"dialogue mismatch (expected '{d_line.get('text', '')[:40]}...')"
                )
            if expected_speaker and actual_speaker and expected_speaker != actual_speaker:
                print(
                    f"  [warn] Scene {scene.get('scene_id')} turn {turn_idx}: "
                    f"speaker mismatch (expected {expected_speaker}, got {actual_speaker})"
                )
            turn_idx += 1

        end_turn = max(start_turn, turn_idx - 1)
        scene["start_turn"] = start_turn
        scene["end_turn"] = end_turn
        scene.pop("dialogues", None)
        scene.pop("dialogue_list", None)
        aligned.append(scene)

    if turn_idx < len(dialogue):
        print(f"  [warn] {len(dialogue) - turn_idx} dialogue turn(s) not assigned to any scene")
    return aligned


def generate_english_storyboard(script: dict, *, portrait: bool = False) -> dict:
    """Post-dialogue Groq call: group dialogue into Pixar-style visual scenes."""
    dialogue = script.get("dialogue", [])
    if not dialogue:
        script.setdefault("scenes", [])
        return script

    turns_summary = "\n".join(
        f"{i}: [{line.get('speaker', '?')}] {line.get('text', '')[:150]}"
        for i, line in enumerate(dialogue[:120])
    )
    style_suffix = (
        ENGLISH_STORYBOARD_STYLE_SUFFIX_PORTRAIT
        if portrait
        else ENGLISH_STORYBOARD_STYLE_SUFFIX_LANDSCAPE
    )
    theme = script.get("theme") or script.get("title", "English Lesson")
    
    # Calculate appropriate scene count based on dialogue length
    num_turns = len(dialogue)
    if num_turns <= 6:
        scene_count_range = f"{max(2, num_turns // 2)}-{num_turns}"
    elif num_turns <= 12:
        scene_count_range = f"{num_turns // 2}-{num_turns}"
    else:
        scene_count_range = "8-12"

    prompt = f"""You are an expert AI storyboard director for a 3D Pixar-style YouTube channel.
Analyze the input script. For each dialogue row, generate a highly descriptive visual prompt.

TOPIC / THEME: {theme}

DIALOGUE TURNS (index: [Speaker] text):
{turns_summary}

CRITICAL RULES:
1. Always maintain character consistency: Emma has brown hair in a neat ponytail. Liam has short blonde hair. Guest is always female.
2. The style must ALWAYS be: "{style_suffix}"
3. The background and character actions must match the literal words spoken in the dialogue text.
4. Create {scene_count_range} scenes total for visual variety (roughly 1-2 dialogue turns per scene). NEVER exceed the total number of dialogue turns ({num_turns}).
5. Change scenes frequently to maintain viewer engagement - every 15-20 seconds in the final video.
6. Each scene needs a descriptive image_filename like scene_1_library_discussion.png (lowercase, underscores, strictly .png extension).
7. Each scene must specify the 'start_turn' and 'end_turn' as the integer dialogue turn indices (matching the DIALOGUE TURNS list indices above) that are covered by this scene. Ensure the scenes sequentially cover all turns from 0 to {num_turns - 1}.
8. NEVER include references to narrator in visual prompts.
9. QUIZ TIMING RULE: For quiz formats, scenes showing the correct answer, checkmarks, or results MUST only appear in scenes that start AFTER the answer has been revealed in the dialogue (i.e., after the turn where the narrator announces the correct answer).
10. SPOILER PREVENTION: Scenes covering "pause" turns (e.g., "[PAUSE 3 SECONDS]") must NOT reveal answers, show checkmarks, highlight correct options, or display any outcomes. They should only show the question/presentation state.
11. CONTENT SEQUENCING: Visual prompts must only depict content that has already been mentioned or is actively being discussed in the dialogue turns covered by that scene. Do not show future events or outcomes.
12. SUMMARY SCENE: You MUST add one final scene with "scene_label": "Summary Card". Its "start_turn" MUST be set to the turn where the Narrator begins the closing/summary line (e.g. "Here's what we learned..."), and "end_turn" should be the last dialogue turn. This ensures the summary card background displays while the Narrator delivers the closing lines. Its "visual_prompt" should describe an atmospheric, warm, inviting background inspired by the story's setting — NO characters, NO text, just the environment with soft golden lighting and a storybook feel. This image will be used as the background for the "What We Learned Today" summary card.

Output ONLY valid JSON with this schema:
{{
  "theme": "string",
  "scenes": [
    {{
      "scene_id": 1,
      "scene_label": "string (short chapter label for YouTube timeline, e.g. Crisis Hook)",
      "image_filename": "scene_1_library_discussion.png",
      "visual_prompt": "string (ONE highly descriptive 3D Pixar-style prompt ending with: {style_suffix})",
      "start_turn": 0,
      "end_turn": 2
    }},
    {{
      "scene_id": N,
      "scene_label": "Summary Card",
      "image_filename": "scene_summary.png",
      "visual_prompt": "string (atmospheric background only — no characters, no text. Warm golden lighting, storybook aesthetic, matching the story setting)",
      "start_turn": {num_turns - 1},
      "end_turn": {num_turns - 1}
    }}
  ]
}}
"""
    try:
        res = call_groq_json(prompt)
        scenes = res.get("scenes", [])
        if not isinstance(scenes, list):
            scenes = []
        for scene in scenes:
            vp = str(scene.get("visual_prompt", "")).strip()
            # Remove any narrator, caption, or text references to prevent them from appearing in generated images
            vp = re.sub(r"\bnarrator'?s?\b[^,.]*", '', vp, flags=re.IGNORECASE)
            vp = re.sub(r'\s+,', ',', vp)  # Clean up commas after removals
            vp = re.sub(r'\s{2,}', ' ', vp)  # Clean up extra spaces
            vp = re.sub(r',\s*\.', '.', vp)  # Clean up dangling commas
            vp = vp.strip()
            if vp and style_suffix.lower() not in vp.lower():
                scene["visual_prompt"] = f"{vp.rstrip('.')} {style_suffix}"
            elif vp:
                scene["visual_prompt"] = vp
        # Summary card is only used for landscape long-form — skip for portrait/shorts
        if portrait:
            scenes = [s for s in scenes if str(s.get("scene_label", "")).lower() != "summary card"]
        script["theme"] = res.get("theme") or theme
        script["scenes"] = align_scenes_to_turns(scenes, dialogue)
        print(f"  Storyboard: {len(script['scenes'])} scene(s) generated")
    except Exception as exc:
        print(f"  Storyboard generation skipped (Groq error): {exc}")
        script.setdefault("scenes", [])
    return script


def attach_storyboard_to_script(script: dict, *, portrait: bool = False) -> dict:
    """Generate storyboard scenes and apply description post-processing."""
    script = generate_english_storyboard(script, portrait=portrait)
    video_format = script.get("video_format", "")
    is_quiz = video_format in ("shorts_quiz",)
    is_shorts = video_format in ("shorts", "shorts_quiz")
    desc_format = "quiz" if is_quiz else ("shorts" if is_shorts else "longform")
    theme = script.get("theme") or script.get("title", "")
    if script.get("description"):
        script["description"] = finalize_english_description(
            script["description"],
            include_timeline=False,  # Timeline handled separately by _inject_scene_timeline in manual_run.py
            is_quiz=is_quiz,
            is_shorts=is_shorts,
            format=desc_format,
            theme=theme,
        )
    return script


def get_published_topics() -> dict:
    """Load published English topics grouped by content type."""
    if PUBLISHED_TOPICS_FILE.exists():
        try:
            with open(PUBLISHED_TOPICS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    if "quiz" not in data:
                        data["quiz"] = []
                    return data
                # Handle old list format by migrating it to "podcast"
                return {"podcast": data, "shorts": [], "challenge": [], "slow": [], "quiz": [], "post": []}
        except Exception as e:
            print(f"Error loading published topics: {e}")
    return {"podcast": [], "shorts": [], "challenge": [], "slow": [], "quiz": [], "post": []}

def is_already_published(topic: str, topic_type: str) -> bool:
    """Check if a topic or title already exists in the published history for a specific type."""
    topics_data = get_published_topics()
    published = topics_data.get(topic_type, [])
    topic_lower = topic.lower().strip()
    for entry in published:
        entry_lower = str(entry).lower().strip()
        if topic_lower in entry_lower or entry_lower in topic_lower:
            return True
    return False

def save_published_topic(topic: str, topic_type: str = "podcast"):
    topics_data = get_published_topics()
    if topic_type not in topics_data:
        topics_data[topic_type] = []
        
    if topic not in topics_data[topic_type]:
        topics_data[topic_type].append(topic)
        try:
            with open(PUBLISHED_TOPICS_FILE, "w", encoding="utf-8") as f:
                json.dump(topics_data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Error saving published topic: {e}")


ENGLISH_TOPIC_POOL = []

COMMUNITY_POLL_POOL = []

WEEKLY_CHALLENGE_TOPIC_POOL = []

# Mid-episode sign-offs the model often adds at part boundaries.
_OUTRO_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bsubscribe\b",
        r"\blike\s+(?:and\s+)?subscribe\b",
        r"\bhit\s+the\s+(?:like|bell)\b",
        r"\bnotification\s+bell\b",
        r"\bthanks?\s+for\s+(?:listening|watching|tuning\s+in|joining)\b",
        r"\btune\s+in\s+(?:next|for\s+more|again)\b",
        r"\bstay\s+tuned\b",
        r"\bnext\s+epis(?:ode|ide)\b",
        r"\bin\s+(?:the\s+)?(?:next|future|upcoming)\s+(?:episode|lesson|video|part)\b",
        r"\b(?:we|we'll|we\s+will)\s+(?:explore|cover|talk\s+about|look\s+at|continue)\b.*\bnext\b",
        r"\b(?:next|after\s+the)\s+break\b",
        r"\b(?:take|taking|let'?s\s+take)\s+a\s+(?:quick\s+)?break\b",
        r"\bwe'?ll\s+be\s+right\s+back\b",
        r"\bsee\s+you\s+(?:next|soon|later)\b",
        r"\blooking\s+forward\s+to\s+(?:it|next|seeing\s+you|continuing)\b",
        r"\buntil\s+next\s+time\b",
        r"\bdon'?t\s+forget\s+to\s+(?:like|subscribe)\b",
        r"\bEnglishVibesHub\b.*\b(?:bye|goodbye|see\s+you)\b",
        r"\b(?:bye|goodbye)\b.*\bEnglishVibesHub\b",
    )
]

_CTA_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bsubscribe\b",
        r"\blike\s+(?:and\s+)?subscribe\b",
        r"\bhit\s+the\s+(?:like|bell)\b",
        r"\bnotification\s+bell\b",
        r"\bdon'?t\s+forget\s+to\s+(?:like|subscribe)\b",
        r"\btune\s+in\s+(?:next|for\s+more|again)\b",
        r"\bstay\s+tuned\b",
        r"\bnext\s+epis(?:ode|ide)\b",
        r"\bsee\s+you\s+(?:next|soon|later)\b",
    )
]

# Motivational/preachy patterns that cause viewer drop-off
_MOTIVATIONAL_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bremember\b.*\bkey\b",
        r"\bkey\s+to\s+mastering\b",
        r"\bpractice.*practice.*practice\b",
        r"\bkeep\s+practicing\b",
        r"\bmove\s+on\s+to\s+(?:more\s+)?advanced\b",
        r"\bthe\s+key\s+is\b",
        r"\bimportant\s+to\s+remember\b",
        r"\bdon'?t\s+give\s+up\b",
        r"\bkeep\s+going\b",
        r"\byou\s+can\s+do\s+it\b",
        r"\bstay\s+motivated\b",
        r"\bnever\s+stop\s+learning\b",
        r"\bconsistency\s+is\s+key\b",
        r"\bpractice\s+makes\s+perfect\b",
        r"\bthe\s+more\s+you\s+practice\b",
        r"\bkeep\s+up\s+the\s+good\s+work\b",
        r"\byou'?re\s+doing\s+great\b",
        r"\bkeep\s+up\s+the\s+momentum\b",
        r"\blet'?s\s+keep\s+practicing\b",
        r"\bremember\s+to\s+practice\b",
    )
]

_NOT_FINAL_PART_RULES = """
CONTINUITY (THIS IS NOT THE FINAL PART OF THE VIDEO):
- Treat this as one invisible chunk inside a single continuous long-form video, not as a standalone episode.
- Do NOT thank listeners for watching or say goodbye.
- Do NOT ask viewers to like, subscribe, or hit the bell.
- Do NOT say "see you next time", "tune in next episode", "stay tuned", "let's take a break", "we'll be right back", "next episode", or similar closings.
- Do NOT preview future videos, future episodes, or a later break.
- Do NOT use motivational or preachy language like "remember the key to mastering", "practice practice practice", "keep practicing", "move on to advanced", "don't give up", "you can do it", "stay motivated", "never stop learning", "consistency is key", "practice makes perfect", "keep up the good work", "you're doing great", or similar encouragement phrases.
- End on an open conversation beat or unfinished teaching moment so the next generated part continues naturally.
"""


def is_outro_line(text: str) -> bool:
    return any(p.search(text) for p in _OUTRO_PATTERNS)


def is_cta_line(text: str) -> bool:
    return any(p.search(text) for p in _CTA_PATTERNS)


def is_motivational_line(text: str) -> bool:
    return any(p.search(text) for p in _MOTIVATIONAL_PATTERNS)


def generate_dynamic_topic(is_challenge: bool = False, topic_type: str = "podcast") -> str:
    """Ask Groq to generate a fresh, high-CTR English learning topic.

    The prompt shows diverse topic areas as inspiration and lets the LLM
    choose freely, relying on the avoidance list to prevent repetition.
    """
    if topic_type == "post":
        type_label = "YouTube Community quiz or poll"
    elif topic_type == "quiz":
        type_label = "YouTube Shorts quiz"
    elif is_challenge:
        type_label = "7-day weekly challenge"
    else:
        type_label = "podcast episode"

    topics_data = get_published_topics()
    published_topics = topics_data.get(topic_type, [])
    recent_topics = published_topics[-50:] if published_topics else []

    avoid_instruction = ""
    if recent_topics:
        avoid_instruction = f"""
    CRITICAL: Avoid repeating or closely matching any of these previously published topics/titles:
    {json.dumps(recent_topics, indent=2)}
    """

    prompt = f"""
    Generate ONE high-CTR topic for an English learning {type_label}.

    Choose from ANY area — grammar, vocabulary, pronunciation, cultural situations,
    workplace, travel, exam prep, modern slang, everyday scenarios, or storytelling.
    The examples below show the full range; prioritize variety and pick whatever
    will be most clickable for an English-learning audience.

    TOPIC AREA EXAMPLES (use as inspiration, not a checklist):
    - Everyday scenarios: Calling in sick to work, returning clothes, asking a neighbor for help, canceling a subscription, dealing with a rude cashier.
    - Grammar traps: When to use "have been" vs "have gone", "much" vs "many" in real speech, "used to" vs "would" for past habits.
    - Confusing words: "Say" vs "Tell", "Borrow" vs "Lend", "Make" vs "Do", "Fun" vs "Funny", "Advice" vs "Advise".
    - Cultural situations: How to small talk at a Western workplace, tipping etiquette, why Americans avoid "How old are you?", how to decline an invitation.
    - Pronunciation pitfalls: Why "th" breaks your accent, "sheet" vs "seat", why "beach" and "bitch" sound different to natives.
    - Modern slang: What "no cap", "bet", "slay" mean, corporate slang decoded, Gen Z dating English.
    - Story/disaster: Lost in a foreign city, job interview nightmare, English mistake at the hospital.
    - Workplace English: Disagree with your boss, professional email phrases, performance review prep.
    - Travel: Surviving an English-only hotel emergency, lost passport at the airport, asking for directions.
    - Exam prep: IELTS Speaking Part 1 model answers, TOEFL vs IELTS, common writing mistakes.
    - Idioms and expressions: "Break a leg", "Hit the nail on the head", "Bite the bullet", "Under the weather", "Cost an arm and a leg".
    - Phrasal verbs: "Give up", "Run out of", "Look forward to", "Get along with", "Put up with".

    PREVIOUSLY PUBLISHED TOPICS (do not repeat these):
    {avoid_instruction if avoid_instruction else "(none yet)"}

    TITLE RULES (follow these exactly):
    - Maximum 65 characters total. This is critical — YouTube truncates titles on mobile at ~60 chars.
    - Use ONE of these proven high-CTR formulas (vary from what you see in the published list above):
      A. Crisis hook: "I Said [X] and They Got OFFENDED"
      B. Urgency gap: "STOP Using [X] — Here's Why"
      C. Social proof: "Native Speakers NEVER Say [X]"
      D. Curiosity bomb: "The [X] Secret Nobody Teaches"
      E. Story cliffhanger: "Lost in [Situation] Because of [X]"
      F. Mistake shame: "You Sound RUDE When You Say [X]"
      G. Comparison shock: "[A] vs [B]: One Makes You Look Dumb"
      H. Personal failure: "I Embarrassed Myself With [X]"
      I. Challenge: "Only 10% Pass This [X] Test"
      J. Cultural warning: "Don't Say [X] in English (Trust Me)"
    - FORBIDDEN WORDS: NEVER use "practice", "learn", "master", "English lesson", "tutorial", "study" — these kill CTR
    - For quiz shorts, prefer quiz-focused formulas like "Only 10% Pass This [X] Test" or "You're Probably Saying [X] Wrong"
    - Do NOT force "English listening practice" or "Learn English" as the first words — keep keywords organic
    - The title must trigger EMOTION or CURIOSITY, not describe content like a textbook heading
    - Include one natural keyword variant (e.g., if about "restaurant" include "dining", "cafe", "food order")

    Return ONLY a JSON object with these keys:
    - "topic": a short 3-8 word label for the core subject (e.g., "Saying vs telling confusion" or "Job interview confidence phrases")
    - "title": the full YouTube title following the rules above (max 65 chars)
    - "search_keyword": 3-5 word SEO phrase (e.g., "English confusing words say tell difference")

    Example output:
    {{"topic": "Borrow vs lend confusion", "title": "Borrow vs Lend: You're Using One Wrong", "search_keyword": "English confusing words borrow lend"}}
    """
    try:
        res = call_groq_json(prompt)
        return res.get("title") or res.get("topic")
    except Exception as e:
        print(f"  Error generating dynamic topic: {e}. Falling back to seed topic.")
        if topic_type == "quiz":
            return random.choice([
                "Only 10% Pass This Phrasal Verb Test",
                "You're Probably Saying This Idiom Wrong",
                "STOP Making This Grammar Mistake",
                "Confusing Words: One Makes You Look Dumb",
                "Present Perfect vs Past Simple: You're Wrong",
                "Can You Choose the Right Preposition?",
                "Office English: You Sound Rude",
                "5 Business Phrases That Make You Look Smart",
                "Everyday English: You're Using It Wrong",
                "Your Pronunciation Is Killing Your Accent",
            ])
        return random.choice([
            "Say vs Tell: You're Using One Wrong",
            "Small Talk at Work: You Sound AWKWARD",
            "Why TH Breaks Your English Accent",
            "Calling in Sick: You Sound Unprofessional",
            "Have Been vs Have Gone: You're Wrong",
            "Gen Z Slang That Changes Everything",
            "Lost in a Foreign City With No Phone",
            "Disagree With Your Boss: Don't Get Fired",
            "Hotel Emergency: I Almost Got Arrested",
            "IELTS Speaking: You're Losing Points",
        ])


def generate_thumbnail_text(topic: str, is_challenge: bool = False) -> dict:
    """Use Groq to create a short mobile-friendly thumbnail headline."""
    type_label = "weekly challenge episode" if is_challenge else "English conversation episode"
    prompt = f"""
    You are writing a mobile-friendly YouTube thumbnail overlay for an {type_label} about "{topic}".
    Return ONLY a JSON object with these keys:
    - thumbnail_text: 3-5 bold, eye-catching words for a mobile thumbnail overlay.
    - thumbnail_concept: one short sentence describing the visual vibe.

    Rules:
    - Keep thumbnail_text short enough to fit on mobile.
    - Do not use more than 5 words.
    - Avoid punctuation except a single ampersand if needed.
    - Use strong action or emotion words.

    Example:
    {{"thumbnail_text": "Speak Confidently Today", "thumbnail_concept": "Bold white text over a blurred cafe background"}}
    """
    try:
        res = call_groq_json(prompt)
        return {
            "thumbnail_text": str(res.get("thumbnail_text", "")).strip(),
            "thumbnail_concept": str(res.get("thumbnail_concept", "")).strip(),
        }
    except Exception as e:
        print(f"  Error generating thumbnail text: {e}. Falling back to title.")
        return {
            "thumbnail_text": topic,
            "thumbnail_concept": "Bold mobile-friendly overlay text.",
        }


def sanitize_dialogue_part(dialogue: list, max_outro_turns_at_end: int = 0, is_intro: bool = False, is_outro: bool = False) -> list:
    """Drop sign-off / CTA lines; Part 3 may keep them only in the last N turns."""
    if not dialogue:
        return []

    dialogue = flatten_dialogue(dialogue)

    # If this is the very first part of the episode, we want to preserve the 
    # intro turns even if they contain "thanks for joining" language.
    prefix = []
    if is_intro:
        keep_prefix = min(3, len(dialogue))
        prefix = [t for t in dialogue[:keep_prefix] if not is_cta_line(t.get("text", ""))]
        dialogue = dialogue[keep_prefix:]

    # If this is the final part of the episode, we want to preserve the 
    # wrap-up turns even if they contain "thanks for listening" language.
    suffix = []
    if is_outro or max_outro_turns_at_end:
        n_to_keep = max(max_outro_turns_at_end, 3)
        keep_suffix = min(n_to_keep, len(dialogue))
        suffix = dialogue[-keep_suffix:]
        dialogue = dialogue[:-keep_suffix]

    # Filter out mid-episode sign-off lines and motivational/preachy lines from the remaining body
    body = [t for t in dialogue if not is_outro_line(t.get("text", "")) and not is_motivational_line(t.get("text", ""))]
    return prefix + body + suffix


# DEPRECATED: combine_english_parts removed - replaced by single storytelling prompt
# def combine_english_parts(part1_data: dict, part2_data: dict, part3_data: dict, topic: str) -> dict:
#     ... (removed as part of storytelling format migration)

def call_groq_json(user_prompt: str) -> dict:
    res = groq_chat_json(
        messages=[
            {
                "role": "system",
                "content": (
                    "You generate perfect JSON for educational English conversation podcasts. "
                    "Each multi-part episode has exactly ONE closing outro at the very end; "
                    "never add subscribe or goodbye language in middle parts. "
                    "Never use motivational or preachy language like 'remember the key to mastering', "
                    "'practice practice practice', 'keep practicing', 'move on to advanced', 'don't give up', "
                    "'you can do it', 'stay motivated', 'never stop learning', 'consistency is key', "
                    "'practice makes perfect', 'keep up the good work', 'you're doing great', or similar encouragement phrases. "
                    "IMPORTANT: Dialogue text will be read aloud by a text-to-speech engine that interprets "
                    "punctuation as performance cues. Write dialogue that sounds like real speech when read aloud — "
                    "use exclamation marks for energy, ellipses for hesitation, em-dashes for interruptions, "
                    "and short fragments for emotional beats. Vary sentence length within turns."
                ),
            },
            {"role": "user", "content": user_prompt},
        ],
        max_tokens=ENGLISH_MAX_TOKENS,
        temperature=0.7,
    )
    # Ensure we always return a dictionary; sometimes the LLM returns a list of items directly.
    if isinstance(res, list):
        return {"dialogue": res}
    return res


def annotate_script_with_idiom_windows(script_data: dict) -> dict:
    """
    Post-generation Groq call: given the finalized dialogue, ask Groq to
    identify each idiom / phrasal verb and the dialogue turn index range
    when it is first *introduced and explained* (not just mentioned).

    Mutates script_data in-place by adding:
        script_data["idiom_windows"] = [
            {
              "idiom":       "get out of hand",
              "type":        "phrasal_verb",   # or "idiom"
              "definition":  "to become uncontrollable",
              "start_turn":  4,
              "end_turn":    6,
            },
            ...
        ]

    Returns the (mutated) script_data dict.
    Falls back to an empty list on any Groq error — never blocks the pipeline.
    """
    dialogue = script_data.get("dialogue", [])
    if not dialogue:
        script_data.setdefault("idiom_windows", [])
        return script_data

    # Build a compact dialogue summary for the prompt (index + speaker + text)
    max_turns = min(len(dialogue), 80)  # cap to stay within token budget
    turns_summary = "\n".join(
        f"{i}: [{line.get('speaker','?')}] {line.get('text','')[:120]}"
        for i, line in enumerate(dialogue[:max_turns])
    )

    prompt = f"""You are analysing an English learning podcast dialogue.

DIALOGUE TURNS (index: [Speaker] text):
{turns_summary}

TASK:
Identify every idiom or phrasal verb that is explicitly INTRODUCED AND EXPLAINED to the listener in this dialogue (not just casually mentioned). For each one return:
- "idiom":      the exact phrase
- "type":       "idiom" or "phrasal_verb"
- "definition": one concise sentence explaining its meaning
- "start_turn": dialogue turn index where the explanation STARTS (0-based integer)
- "end_turn":   dialogue turn index where the explanation ENDS (inclusive, 0-based integer)

RULES:
- Only include phrases that are actually taught/explained to the listener.
- start_turn and end_turn must be valid 0-based integers within range 0..{max_turns - 1}.
- end_turn must be >= start_turn.
- If no idioms or phrasal verbs are explained, return an empty array.
- Output ONLY valid JSON.

JSON SCHEMA:
{{
  "idiom_windows": [
    {{
      "idiom": "string",
      "type": "idiom or phrasal_verb",
      "definition": "string",
      "start_turn": 0,
      "end_turn": 2
    }}
  ]
}}
"""
    try:
        res = groq_chat_json(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a precise JSON extractor. "
                        "Return only valid JSON with no extra text."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=1024,
            temperature=0.2,
        )
        windows = res.get("idiom_windows", [])
        if not isinstance(windows, list):
            windows = []

        # Clamp turn indices to valid range
        n = len(dialogue)
        cleaned = []
        for w in windows:
            try:
                st = max(0, min(int(w.get("start_turn", 0)), n - 1))
                et = max(st, min(int(w.get("end_turn", st)), n - 1))
                cleaned.append({
                    "idiom":       str(w.get("idiom", "")).strip(),
                    "type":        str(w.get("type", "idiom")).strip(),
                    "definition":  str(w.get("definition", "")).strip(),
                    "start_turn":  st,
                    "end_turn":    et,
                })
            except (TypeError, ValueError):
                continue

        script_data["idiom_windows"] = cleaned
        print(f"  Idiom annotation: {len(cleaned)} window(s) identified")
        
        # Remove summary scene if no idioms/phrasal verbs were found
        if not cleaned:
            scenes = script_data.get("scenes", [])
            summary_idx = None
            for _i, s in enumerate(scenes):
                if str(s.get("scene_label", "")).lower() == "summary card":
                    summary_idx = _i
                    break
            if summary_idx is not None:
                summary_end = scenes[summary_idx].get("end_turn", 0)
                # Extend previous scene so there's no gap after removal
                if summary_idx > 0:
                    prev = scenes[summary_idx - 1]
                    if summary_end > prev.get("end_turn", 0):
                        prev["end_turn"] = summary_end
                        print(f"  Extended scene {summary_idx} end_turn to {summary_end} (absorbing summary range)")
                scenes.pop(summary_idx)
                script_data["scenes"] = scenes
                print(f"  Removed summary scene (no idioms/phrasal verbs to summarize)")
    except Exception as exc:
        print(f"  Idiom annotation skipped (Groq error): {exc}")
        script_data.setdefault("idiom_windows", [])

    return script_data


def separate_mixed_pause_turns(script_data: dict) -> dict:
    """
    Preprocessing step to split dialogue turns where pause marker is mixed with other text.
    The pause marker "[PAUSE 3 SECONDS]" must be on its own turn for proper pause detection.
    
    Example: Turn with text "[PAUSE 3 SECONDS]\nOption C is the best choice..."
    becomes:
      - Turn N: "[PAUSE 3 SECONDS]"
      - Turn N+1: "Option C is the best choice..."
      
    Also handles same-line mixing: "[PAUSE 3 SECONDS] Option C is the best choice..."
    """
    dialogue = script_data.get("dialogue", [])
    if not dialogue:
        return script_data
    
    PAUSE_PATTERN = re.compile(r'^\s*\[PAUSE\s+(\d+(?:\.\d+)?)\s*SECONDS?\]\s*$', re.IGNORECASE)
    SAME_LINE_PAUSE_PATTERN = re.compile(r'(\[PAUSE\s+\d+(?:\.\d+)?\s*SECONDS?\])', re.IGNORECASE)
    
    new_dialogue = []
    turn_offset = 0
    
    for turn in dialogue:
        text = turn.get("text", "")
        
        # First check for same-line mixed pause (e.g., "[PAUSE 3 SECONDS] Option C is...")
        same_line_match = SAME_LINE_PAUSE_PATTERN.search(text)
        if same_line_match and not PAUSE_PATTERN.match(text.strip()):
            # Extract pause marker and remaining text
            pause_marker = same_line_match.group(1)
            remaining_text = text.replace(pause_marker, "", 1).strip()
            
            # Split into two separate turns
            pause_turn = dict(turn)
            pause_turn["text"] = pause_marker
            pause_turn["turn_number"] = turn.get("turn_number", 0) + turn_offset
            new_dialogue.append(pause_turn)
            turn_offset += 1
            
            if remaining_text:
                content_turn = dict(turn)
                content_turn["text"] = remaining_text
                content_turn["turn_number"] = turn.get("turn_number", 0) + turn_offset
                new_dialogue.append(content_turn)
                turn_offset += 1
            
            print(f"  [pause_split] Split same-line mixed pause at turn {turn.get('turn_number')} into separate turns")
            continue
        
        # Check if this is a multi-line mixed pause (pause marker + other text)
        lines = text.split('\n')
        pause_line = None
        remaining_lines = []
        
        for line in lines:
            if PAUSE_PATTERN.match(line.strip()):
                pause_line = line.strip()
            else:
                remaining_lines.append(line)
        
        if pause_line and remaining_lines:
            # Split into two separate turns
            pause_turn = dict(turn)
            pause_turn["text"] = pause_line
            pause_turn["turn_number"] = turn.get("turn_number", 0) + turn_offset
            new_dialogue.append(pause_turn)
            turn_offset += 1
            
            content_turn = dict(turn)
            content_turn["text"] = '\n'.join(remaining_lines).strip()
            content_turn["turn_number"] = turn.get("turn_number", 0) + turn_offset
            new_dialogue.append(content_turn)
            turn_offset += 1
            
            print(f"  [pause_split] Split multi-line mixed pause at turn {turn.get('turn_number')} into separate turns")
        else:
            # No mixed pause, keep as-is with updated turn number
            updated_turn = dict(turn)
            updated_turn["turn_number"] = turn.get("turn_number", 0) + turn_offset
            new_dialogue.append(updated_turn)
    
    script_data["dialogue"] = new_dialogue
    return script_data


def renumber_dialogue_turns(script_data: dict) -> dict:
    """Ensure dialogue turn numbers are sequential starting from 1, with no gaps.

    This fixes LLM-generated scripts where turn numbers skip (e.g. 1,2,3,5,8...).
    Also updates scene start_turn/end_turn references to match the new numbering.
    """
    dialogue = script_data.get("dialogue", [])
    if not dialogue:
        return script_data

    old_to_new = {}
    for i, turn in enumerate(dialogue, start=1):
        old_num = turn.get("turn_number", i)
        old_to_new[old_num] = i
        turn["turn_number"] = i

    # Update scene turn references
    for scene in script_data.get("scenes", []):
        old_start = scene.get("start_turn", 0)
        old_end = scene.get("end_turn", 0)
        scene["start_turn"] = old_to_new.get(old_start, old_start)
        scene["end_turn"] = old_to_new.get(old_end, old_end)

    return script_data


def _clean_challenge_dialogue(script: dict, day_number: int) -> dict:
    cleaned = dict(script)
    cleaned["dialogue"] = sanitize_dialogue_part(
        script.get("dialogue", []),
        max_outro_turns_at_end=2 if day_number == 7 else 0,
        is_intro=day_number != 7,
        is_outro=day_number == 7,
    )
    return cleaned


def generate_weekly_challenge_plan(topic=None) -> dict:
    if not topic:
        topic = generate_dynamic_topic(is_challenge=True, topic_type="challenge")
    else:
        # Check if manual topic is already published
        if is_already_published(topic, "challenge"):
            print(f"\n  [WARNING] Manual challenge topic '{topic}' was found in 'challenge' history.")

    # History injection
    topics_data = get_published_topics()
    recent = topics_data.get("challenge", [])[-50:]
    avoid_instruction = f"\nAvoid repeating content or structure from these recent challenges:\n{json.dumps(recent, indent=2)}" if recent else ""

    print(f"\nSelected weekly challenge topic: {topic} for @EnglishVibesHub-s6w")
    prompt = f"""
Create a high-retention & high-CTR 7-day weekly challenge playlist plan for the YouTube channel 'EnglishVibesHub' (@EnglishVibesHub-s6w).
WEEKLY THEME: {topic}
{avoid_instruction}

CRITICAL RULES:
- Output ONLY valid JSON.
- Day 1 through Day 6 must each teach one focused skill and give listeners one clear daily practice task.
- Day 7 must be a recap episode that reviews the entire week, asks challenge questions, and gives listeners a solid foundation to continue.
- Keep the plan practical for English learners at intermediate levels.

JSON SCHEMA:
{{
  "series_title": "string",
  "description": "string",
  "tags": ["string"],
  "days": [
    {{
      "day": 1,
      "title": "string",
      "focus": "string",
      "practice_task": "string",
      "keywords": ["string"]
    }}
  ]
}}

REQUIREMENTS:
- Exactly 7 days.
- Day values must be 1 through 7.
- Day 7 title must clearly signal recap, questions, or challenge review.
"""
    plan = call_groq_json(prompt)
    days = plan.get("days", [])
    if len(days) != 7:
        raise ValueError(f"Weekly challenge plan must contain exactly 7 days, got {len(days)}")
    return plan


def generate_weekly_challenge_quiz_script(day_script: dict) -> dict:
    """Generate a quiz short script based on a specific day's challenge content."""
    series_title = day_script.get("series_title", "English Challenge")
    day_num = day_script.get("day", 1)
    focus = day_script.get("focus", "English conversation")

    prompt = f"""
    You are an expert short-form scriptwriter. Generate a high-retention, 25-second YouTube Shorts English quiz loop based on Day {day_num} of the '{series_title}' challenge on @EnglishVibesHub-s6w.

    LESSON FOCUS: {focus}
    {ENGLISH_METADATA_RULES}

    TIME ALLOCATION RULES:
    - [0-3s] Hook: Emma introduces the Day {day_num} Challenge question clearly.
    - [3-13s] Sequential Options: Liam presents Options A, B, and C sequentially. Allocate exactly 3.3 seconds per option (Liam should have 3 separate dialogue turns for these).
    - [13-20s] Context Hint: Liam provides an educational example sentence or hint related to "{focus}".
    - [20-25s] Answer Reveal & Perfect Loop CTA: Emma reveals the answer and cuts instantly into a seamless word loop back to the hook.

    PACING:
    The pacing must allow English learners time to read, but remain engaging enough to prevent swipe-aways.
    - Emma's hook should feel like a genuine question, not a script reading — use "Wait, do you know what ___ means?"
    - Liam's options should sound like natural suggestions, not a list being read aloud.

    LEVERAGE COMMENTS: Generate a 'pinned_comment' question to trigger algorithmic signals.

    JSON SCHEMA:
    {{
      "title": "string (Searchable keyword-rich title under 60 characters. Front-load with 'English Quiz' or 'English listening practice'. Include topic first, then Day {day_num} in the suffix at the end. Use keyword variations. e.g., 'English Quiz: Hair Salon Vocabulary - Day {day_num}')",
      "description": "string (Follow METADATA RULES template. First 2 lines MUST use 'Natural English' and 'Speak like a native'. Place comment question in lines 3-5. Include {{scene_timeline}} placeholder for scene chapters, subscribe CTA, playlist placeholder, and hashtags mirroring 'tags')",
      "pinned_comment": "string",
      "tags": ["string (Provide 5-8 SEO-focused English learning tags)"],
      "correct_answer": "string",
      "dialogue": [
        {{ "speaker": "Emma", "text": "..." }},
        {{ "speaker": "Liam", "text": "..." }}
      ]
    }}
    """
    script_data = call_groq_json(prompt)
    # Preprocess to separate mixed pause markers
    script_data = separate_mixed_pause_turns(script_data)
    script_data["video_format"] = "shorts_quiz"
    theme = script_data.get("theme") or script_data.get("title", "")
    script_data["description"] = finalize_english_description(
        script_data.get("description", ""), is_quiz=True, format="quiz", theme=theme
    )
    return attach_storyboard_to_script(script_data, portrait=True)

def generate_english_community_content(topic: str = None, content_type: str = "quiz") -> dict:
    """
    Generates content for YouTube Community Tab: 
    types: 'quiz' (text poll with 1 right answer) or 'image_poll' (visual choices).
    """
    if not topic:
        topic = generate_dynamic_topic(topic_type="post")
    else:
        # Check if manual topic is already published
        if is_already_published(topic, "post"):
            print(f"\n  [WARNING] Manual community topic '{topic}' was found in 'post' history.")

    print(f"\nSelected community topic: {topic}")
    
    prompt = f"""
    Create a highly engaging YouTube Community {content_type.replace('_', ' ')} for 'EnglishVibesHub'.
    TOPIC: {topic}

    REQUIREMENTS:
    - Content must be for intermediate English learners.
    - Provide a question and 4 options. Keep each option extremely concise (max 20 characters) so they fit on mobile image overlays.
    - Provide a 'correct_explanation' that explains WHY the answer is correct (for the pinned comment/post body).
    - Provide 4 'image_prompts' (search keywords for Pexels), one for each option.

    JSON SCHEMA:
    {{
      "question": "string",
      "options": ["string", "string", "string", "string"],
      "correct_index": 0,
      "correct_explanation": "string",
      "image_prompts": ["keyword1", "keyword2", "keyword3", "keyword4"]
    }}
    """
    
    res = call_groq_json(prompt)
    res["content_type"] = content_type
    res["topic"] = topic
    return res


def generate_weekly_challenge_day_script(plan: dict, day: dict, standalone: bool = False) -> dict:
    day_number = int(day.get("day", 1))
    series_title = plan.get("series_title", "EnglishVibesHub Weekly Challenge")
    previous_days = [
        f"Day {d.get('day')}: {d.get('title')} - {d.get('focus')}"
        for d in plan.get("days", [])
        if int(d.get("day", 0)) < day_number
    ]

    # History injection
    topic_type = "traditional" if standalone else "challenge"
    topics_data = get_published_topics()
    recent = topics_data.get(topic_type, [])[-50:]
    avoid_instruction = f"\nAvoid repeating content or phrasal verbs/idioms from these recent episodes:\n{json.dumps(recent, indent=2)}" if recent else ""

    if standalone:
        # Standalone mode: remove playlist/day references
        structure = f"""
STRUCTURE & CONTENT:
1. Welcome listeners to this English lesson on @EnglishVibesHub-s6w.
2. Teach the focused skill: {day.get('focus')}.
3. Explain useful phrases, idioms, pronunciation tips, or sentence patterns connected to the skill. Use simple, direct phrasing like "Here 'X' means 'Y'" or "In this context, 'X' means 'Y'". Do NOT use meta-language like "phrasal verb breakdown", "phrase verb spotlight", "break down", or similar educational terminology.
4. Include short roleplay moments between Emma and Liam.
5. Give listeners a practical task to try: {day.get('practice_task')}.
6. End naturally without setting up future content or saying goodbye.
"""
        outro_rule = _NOT_FINAL_PART_RULES
        turn_count = "18-22"
        title_suffix = ""
        series_reference = ""
    elif day_number == 7:
        structure = f"""
STRUCTURE & CONTENT:
1. Welcome listeners to Day 7 of the weekly challenge on @EnglishVibesHub-s6w and name the playlist: {series_title}.
2. Recap Days 1-6 using these exact learning points:
{chr(10).join('- ' + item for item in previous_days)}
3. Ask at least 8 practical challenge questions. Include a short pause cue after each question, then have the hosts explain a strong sample answer.
4. End by giving listeners a simple foundation plan for what to review next week.
5. The final 1-2 dialogue turns may thank listeners and invite them to keep learning with EnglishVibesHub.
"""
        outro_rule = "Do NOT use like/subscribe/goodbye language until the final 1-2 turns."
        turn_count = "20-25"
        title_suffix = f" - Day {day_number}"
        series_reference = f"SERIES: {series_title}\nDAY: {day_number}\n"
    else:
        structure = f"""
STRUCTURE & CONTENT:
1. Welcome listeners to Day {day_number} of the weekly challenge on @EnglishVibesHub-s6w and name the playlist: {series_title}.
2. Teach the focused skill: {day.get('focus')}.
3. Explain useful phrases, idioms, pronunciation tips, or sentence patterns connected to the skill. Use simple, direct phrasing like "Here 'X' means 'Y'" or "In this context, 'X' means 'Y'". Do NOT use meta-language like "phrasal verb breakdown", "phrase verb spotlight", "break down", or similar educational terminology.
4. Include short roleplay moments between Emma and Liam.
5. Give listeners this daily practice task clearly near the end: {day.get('practice_task')}.
6. End by setting up tomorrow's challenge without saying goodbye.
"""
        outro_rule = _NOT_FINAL_PART_RULES
        turn_count = "18-22"
        title_suffix = f" - Day {day_number}"
        series_reference = f"SERIES: {series_title}\nDAY: {day_number}\n"

    if standalone:
        prompt_intro = "You are writing a standalone English lesson video script for 'EnglishVibesHub' (@EnglishVibesHub-s6w)."
        title_instruction = "string (Traditional educational title under 60 characters. Use clear, descriptive titles like 'Airport English for Beginners' or 'Doctor Office Vocabulary Guide'. Include topic keywords naturally. e.g., 'Airport English: Essential Phrases for Travel')"
        script_context = "The script should feel complete as a standalone educational video."
    else:
        prompt_intro = "You are writing a standalone video script for a 7-day English learning challenge playlist on 'EnglishVibesHub' (@EnglishVibesHub-s6w)."
        title_instruction = f"string (High-CTR title under 60 characters. Front-load with 'English listening practice', 'English speaking practice', or 'Learn English'. Include Day {day_number} in the suffix at the end. Use benefit-focused hooks like 'Master This', 'Complete Guide', 'Essential Phrases'. Include keyword variations like 'hairdresser/stylist' for hair salon topics. e.g., 'English Listening Practice: Master Restaurant Vocabulary - Day {day_number}')"
        script_context = "The script should feel complete as one daily video, but connected to the weekly playlist."

    prompt = f"""
{prompt_intro}

{series_reference}TITLE: {day.get('title')}
{avoid_instruction}
FOCUS: {day.get('focus')}
PRACTICE TASK: {day.get('practice_task')}
{ENGLISH_METADATA_RULES}

CRITICAL RULES:
- Output ONLY valid JSON.
- The `dialogue` array MUST contain around {turn_count} turns.
- Hosts must be Emma (energetic, helpful) and Liam (curious, friendly).
- {script_context}
- Keep explanations clear for intermediate English learners.
- Ask listeners to answer out loud when useful.
{outro_rule}

{structure}

STYLE:
- Warm, conversational, practical, and encouraging.
- Avoid short 1-sentence replies. Each turn should usually be 2-4 sentences.

JSON SCHEMA:
{{
  "title": "{title_instruction}",
  "title_options": ["string"],
  "description": "string (Follow METADATA RULES template. First 2 lines MUST use 'Natural English' and 'Speak like a native'. Place comment question in lines 3-5. Include {{scene_timeline}} for scene chapters, subscribe CTA, playlist placeholder, and hashtags mirroring 'tags')",
  "pinned_comment": "string (An engaging question or call to action to pin in the comments)",
  "tags": ["string (Provide 5-8 SEO-focused tags)"],
  "theme": "string (short topic label for storyboard, e.g. 'Phrasal Verbs at Work')",
  "dialogue": [
    {{
      "speaker": "Emma or Liam",
      "text": "string"
    }}
  ]
}}
"""
    script = call_groq_json(prompt)
    # Preprocess to separate mixed pause markers
    script = separate_mixed_pause_turns(script)
    
    if not standalone:
        script.setdefault("day", day_number)
        script.setdefault("series_title", series_title)
    
    script.setdefault("tags", plan.get("tags", ["English", "English Challenge", "EnglishVibesHub"] if not standalone else ["English", "English Learning", "EnglishVibesHub"]))
    theme = script.get("theme") or script.get("title", "")
    script["description"] = finalize_english_description(
        script.get("description", ""), include_timeline=True, format="longform", theme=theme
    )

    if not script.get("title"):
        title_options = script.get("title_options") or []
        if title_options:
            script["title"] = title_options[0]

    if not standalone:
        script = _clean_challenge_dialogue(script, day_number)
    
    return attach_storyboard_to_script(script, portrait=False)


def generate_traditional_english_script(topic=None) -> dict:
    """Generate a standalone traditional English learning script using Emma/Liam format."""
    if not topic:
        topic = generate_dynamic_topic(is_challenge=False, topic_type="traditional")
    else:
        # Check if manual topic is already published
        if is_already_published(topic, "traditional"):
            print(f"\n  [WARNING] Manual topic '{topic}' was found in 'traditional' history.")

    # History injection
    topics_data = get_published_topics()
    recent = topics_data.get("traditional", [])[-50:]
    avoid_instruction = f"\nAvoid repeating examples, phrases, or situations used in these recent episodes:\n{json.dumps(recent, indent=2)}" if recent else ""

    print(f"\nSelected topic: {topic}")
    print("Generating traditional educational script...")

    # Create a minimal plan structure for standalone use
    day = {
        "day": 1,
        "title": topic,
        "focus": topic,
        "practice_task": f"Practice using phrases related to {topic} in your daily conversations"
    }
    
    plan = {
        "series_title": "EnglishVibesHub Traditional Lessons",
        "tags": ["English", "English Learning", "EnglishVibesHub"]
    }

    script = generate_weekly_challenge_day_script(plan, day, standalone=True)
    
    # Clean up any remaining day/series references
    script.pop("day", None)
    script.pop("series_title", None)
    
    # Remove summary scene since traditional format doesn't use idioms
    if "scenes" in script:
        script["scenes"] = [s for s in script["scenes"] if "summary" not in str(s.get("scene_label", "")).lower()]
        print(f"  Removed summary scene (traditional format doesn't use idioms)")
    
    return script


def generate_weekly_challenge_scripts(topic=None) -> dict:
    plan = generate_weekly_challenge_plan(topic)
    scripts = []

    for day in plan["days"]:
        day_number = int(day.get("day", len(scripts) + 1))
        print(f"Generating weekly challenge Day {day_number}: {day.get('title')}")
        day_script = generate_weekly_challenge_day_script(plan, day)
        print(f"  Generating accompanying Quiz Short for Day {day_number}...")
        day_script["quiz_script"] = generate_weekly_challenge_quiz_script(day_script)
        scripts.append(day_script)
        if day_number < 7:
            groq_part_cooldown(f"Day {day_number + 1}")

    return_data = {
        "series_title": plan.get("series_title", "EnglishVibesHub Weekly Challenge"),
        "description": plan.get("description", ""),
        "tags": plan.get("tags", []),
        "days": plan["days"],
        "scripts": scripts,
    }
    
    return return_data


def generate_english_script(topic=None):
    if not topic:
        topic = generate_dynamic_topic(is_challenge=False, topic_type="podcast")
    else:
        # Check if manual topic is already published
        if is_already_published(topic, "podcast"):
            print(f"\n  [WARNING] Manual topic '{topic}' was found in 'podcast' history.")

    # History injection
    topics_data = get_published_topics()
    recent = topics_data.get("podcast", [])[-50:]
    avoid_instruction = f"\nAvoid repeating examples, idioms, or stories used in these recent episodes:\n{json.dumps(recent, indent=2)}" if recent else ""

    print(f"\nSelected topic: {topic}")
    print("Generating storytelling script...")

    prompt_short_story = f"""
You are an elite showrunner and scriptwriter for the multi-character storytelling channel EnglishVibesHub (@EnglishVibesHub-s6w). Write a highly engaging, non-linear, dramatic English audio-story script.

TOPIC: {topic}
{avoid_instruction}

VOICE CAST:
- "Narrator": Third-person only. Bridges scenes, weaves explanations INTO narrative flow (never pauses story for lessons).
- "Emma" & "Liam": Main protagonists. 100% first-person. Argue, collaborate, panic. Emma = reactive ("Oh," "Wait,"), short when panicked. Liam = analytical ("Hmm," "Right,"), rhetorical when excited.
- "Guest": Secondary character (shopkeeper, stranger, etc.). REQUIRED in public settings. ALWAYS female. Match register to role.

NATURAL EXPRESSION REQUIREMENTS:
- 2-3 phrasal verbs + 1-2 idioms used naturally in context
- Characters speak like real people in stressful situations, not textbook examples

VOCAL DELIVERY FOR TTS (text will be read aloud — write for the ear):
- ! = pitch/energy boost. ... = slows/softens. — = mid-sentence break. Mix these per emotional beat.
- Use short fragments for shock ("No way." "Wait, what?"), interjections ("Oh," "Hmm," "Ah,"), and vary sentence length within each turn.
- Max 1 **double-asterisk** emphasis per turn on the most emotionally important phrase (e.g., "I can't believe you **actually said that**").

TOPIC ALIGNMENT (MANDATORY):
- Story must directly embody the TOPIC — characters encounter/experience the specific concept.
- Quiz tests the TOPIC expression, not a random phrasal verb. Narrator's closing references what was learned.
- If TOPIC describes a mistake, characters must make/encounter that mistake (genuine example, not mislabeled).
- Quiz: exactly ONE correct answer. Distractors must be clearly wrong, not just "less ideal".

CRITICAL RULES:
1. Output ONLY valid JSON. 2. At least 28 turns, 2-4 sentences each (doubled for longer, more comprehensive content). 3. Narrator = third-person only. Characters = first-person only. Characters never teach. 4. Narrator weaves explanations INTO narrative — never pauses story for a lesson. Include more detailed examples and cultural context throughout. 5. Interactive challenge — EXACT sequence: (a) Narrator cues challenge, (b) Emma or Liam says "Option A: [text]" on their own turn (speaker field must be "Emma" or "Liam"), (c) Emma or Liam says "Option B: [text]" on their own turn (speaker field must be "Emma" or "Liam"), (d) Emma or Liam says "Option C: [text]" on their own turn (speaker field must be "Emma" or "Liam"), (e) Emma or Liam has a turn with text exactly "[PAUSE 3 SECONDS]" (speaker field must be "Emma" or "Liam"), (f) Narrator reveals answer. NEVER put pause before options. NEVER combine options into one turn. NEVER use "Option A", "Option B", "Option C", or "[PAUSE 3 SECONDS]" as speaker field values - always use character names.

STRUCTURAL STAGES:
1. Crisis Hook: SHORT 1-2 sentence turns, rapid back-and-forth, high-stakes energy.
2. Complications: Obstacle worsens, organic reactions, natural expressions.
3. Organic Teaching: Narrator contextualizes idioms as part of ongoing narrative.
4. Climax & Challenge: Peak tension + expression challenge.
5. Resolution: Natural close. Narrator's final 1-line bridge plays OVER Summary Card. No sign-offs.

AVD-FOCUSED PACING (for longer content retention):
- Add engagement hooks every 30-45 seconds to prevent viewer drop-off
- Include interactive questions and challenges throughout the story
- Maintain narrative momentum with cliffhangers between sections
- Use varied pacing to prevent monotony in the longer format
- Apply quiz-style engagement triggers (pinned comment questions, viewer participation)

TITLE OPTIMIZATION (apply shorts/quiz success factors):
- Use proven high-CTR formulas: mistake hooks, curiosity gaps, "Master This", "Complete Guide"
- Include generic English-learning keywords: "English Practice", "Easy English", "English Listening"
- Focus on universally appealing topics that resonate with broader audience

JSON FORMAT:
{{
  "title": "string (under 70 chars, matches METADATA RULES)",
  "description": "string",
  "pinned_comment": "string",
  "tags": ["string"],
  "dialogue": [
    {{"turn_number": 1, "speaker": "Narrator", "text": "..."}},
    {{"turn_number": 2, "speaker": "Emma or Liam", "text": "..."}}
  ],
  "thumbnail_text": "TEXT",
  "thumbnail_concept": "CONCEPT",
  "theme": "2-5 word label matching TOPIC",
  "scenes": [
    {{"scene_id": 1, "scene_label": "string", "image_filename": "scene.png", "visual_prompt": "3D Pixar-style prompt", "start_turn": 1, "end_turn": 2}}
  ]
}}
"""
    is_valid = False
    attempts = 0

    while not is_valid and attempts < 3:
        attempts += 1
        print(f"🔄 Generation Attempt {attempts}...")

        # Multi-part Groq call: Part 1 - Generate dialogue with higher turn count
        raw_script = call_groq_json(prompt_short_story)
        # Preprocess to separate mixed pause markers before validation
        raw_script = separate_mixed_pause_turns(raw_script)
        script, is_valid = validate_organic_english_script(raw_script)

    if not is_valid:
        print("⚠️ Groq failed to generate a perfect script after 3 tries. Using last attempt.")

    # ── POST-PROCESS: description pipeline (same as shorts/quiz) ──
    theme = script.get("theme") or script.get("title", "")
    if script.get("description"):
        script["description"] = finalize_english_description(
            script["description"],
            include_timeline=False,
            is_quiz=False,
            format="longform",
            theme=theme,
        )

    return attach_storyboard_to_script(script, portrait=False)


# ─────────────────────────────────────────────
# SLOW ENGLISH PIPELINE — A1-A2 Listening Practice
# ─────────────────────────────────────────────

SLOW_ENGLISH_METADATA_RULES = """
Title (under 70 chars, rotate): A) "English You Can ACTUALLY Understand: {topic}" B) "Your First English Conversation: {topic}" C) "This Is How {topic} Sounds in Slow English" D) "Can You Follow This? Slow English — {topic}" E) "Finally Understand English: {topic} (Slow & Clear)" F) "A Day at [Place]: Slow English Story for Beginners" G) "[X] Minutes of Slow English You'll Love: {topic}" H) "1000s of Beginners Learned English With This: {topic}". ALL CAPS on 1-2 power words. No "|".
Description: First line must match a beginner search query (e.g. "slow english {topic}", "easy english listening practice for beginners"). Second line = benefit statement. Include 2-3 long-tail keywords naturally (slow english listening practice, english for beginners, a1 english, learn english with stories). Timeline: {scene_timeline}. Playlist: {playlist_url}. 5 hashtags: #EnglishForBeginners #SlowEnglish #<TopicRelated> #SpeakEnglishNaturally #EnglishVibesHub.
"""

SLOW_ENGLISH_STORYBOARD_STYLE_SUFFIX_LANDSCAPE = (
    "Soft watercolor illustration style, warm pastel colors, simple clean lines, calm and friendly atmosphere, 16:9 aspect ratio."
)

# A1-A2 core vocabulary ceiling — the prompt will be instructed to use ONLY these words
# plus proper nouns and the topic-specific vocabulary listed per topic.
SLOW_ENGLISH_TOPICS = [
    "Daily Routine",
    "At the Coffee Shop",
    "My Family",
    "At the Grocery Store",
    "My Home",
    "The Weather Today",
    "Getting Dressed",
    "Breakfast Time",
    "On My Way to Work",
    "At the Park",
    "At the Restaurant",
    "Going Shopping",
    "At the Doctor",
    "My Weekend",
    "At the Airport",
]


def generate_slow_english_script(topic=None):
    """Generate a slow English A1-A2 listening practice script.

    Two-character dialogue (Emma & Liam) discussing a single everyday topic
    at a deliberately slow pace with simple vocabulary and short sentences.
    """
    if not topic:
        # Pick from curated slow English topics, avoiding recently published ones
        topics_data = get_published_topics()
        published_slow = topics_data.get("slow", [])[-30:]
        remaining = [
            t for t in SLOW_ENGLISH_TOPICS
            if not any(t.lower() in p.lower() for p in published_slow)
        ]
        if not remaining:
            remaining = SLOW_ENGLISH_TOPICS
        topic = random.choice(remaining)
    else:
        if is_already_published(topic, "slow"):
            print(f"\n  [WARNING] Manual slow English topic '{topic}' was found in 'slow' history.")

    # History injection
    topics_data = get_published_topics()
    recent = topics_data.get("slow", [])[-30:]
    avoid_instruction = f"\nAvoid repeating vocabulary or phrases from these recent episodes:\n{json.dumps(recent, indent=2)}" if recent else ""

    print(f"\nSelected Slow English topic: {topic}")
    print("Generating A1-A2 slow dialogue script...")

    prompt = f"""A1-A2 slow English dialogue, 18-24 turns, EnglishVibesHub. Topic: {topic}
{avoid_instruction}
{SLOW_ENGLISH_METADATA_RULES.replace('{scene_timeline}', '{{scene_timeline}}').replace('{playlist_url}', '{{playlist_url}}')}

HOOK: No "Hello!" openers. Start with a question creating an open loop. PACING: Vary rhythm every 4-5 turns. ENGAGEMENT: 1-2 viewer questions. [PAUSE 3 SECONDS] for repetition (preceded by Liam modeling).
VOCABULARY: 1,200 common words only. 5-12 word sentences, SVO. Present simple only. Contractions: I'm, you're, it's, that's, we're, don't, can't. Key words repeat 3-5x. Teach through context ("Brother? Your brother is a boy in your family."), never tautologies.
CHARACTERS: Emma (af_heart) = warm teacher. Liam (am_michael) = curious learner who makes mistakes. No single-word commands.
DIALOGUE (18-24 turns): Stage1 HOOK(3-4): question→greeting→topic intro. Stage2 MAIN(8-12): discussion, "how do I say?" 2x, surprises, viewer question. Stage3 PRACTICE(5-7): Emma:"Repeat after me: X"→Liam repeats→[PAUSE 3 SECONDS]. Stage4 KEYWORDS(2-3): list 3-5 words. Stage5 GOODBYE(2-3): tease next, comment CTA.
SCENES: 5-6 scenes, 2-5 turns each. Labels: "The Hook", "Let's Talk About [Topic]", "Your Turn to Practice", "Words You Learned". Calm watercolor prompts.
Turn numbers: sequential from 1, no gaps.

JSON: {{{{ "title":"...", "description":"...", "pinned_comment":"...", "tags":["slow english","english for beginners","a1 english","easy english listening","topic"], "theme":"...", "visual_keywords":["..."], "dialogue":[{{"turn_number":1,"speaker":"Emma","text":"..."}},{{"turn_number":2,"speaker":"Liam","text":"..."}}...MUST have 18-24 entries], "scenes":[{{"scene_id":1,"scene_label":"The Hook","image_filename":"scene_1.png","visual_prompt":"...","start_turn":1,"end_turn":3}}] }}}}
"""

    is_valid = False
    attempts = 0

    while not is_valid and attempts < 3:
        attempts += 1
        print(f"  🔄 Generation Attempt {attempts}...")

        raw_script = call_groq_json(prompt)
        raw_script = separate_mixed_pause_turns(raw_script)
        raw_script = renumber_dialogue_turns(raw_script)
        script, is_valid = validate_slow_english_script(raw_script)

    if not is_valid:
        print("  ⚠️ Groq failed to generate a valid slow English script after 3 tries. Using last attempt.")

    # Set slow English visual style
    for scene in script.get("scenes", []):
        vp = scene.get("visual_prompt", "")
        if vp and "watercolor" not in vp.lower() and "soft" not in vp.lower():
            scene["visual_prompt"] = vp.rstrip(".") + ". " + SLOW_ENGLISH_STORYBOARD_STYLE_SUFFIX_LANDSCAPE

    theme = script.get("theme") or topic
    script["description"] = finalize_english_description(
        script.get("description", ""), theme=theme, format="longform", is_slow_english=True
    )

    return attach_storyboard_to_script(script, portrait=False)


def validate_slow_english_script(raw_input):
    """Validation engine for slow English A1-A2 scripts.

    Simpler than the full English validator — checks for:
    - Minimum turn count (16+)
    - Only Emma and Liam as speakers
    - Simple sentences (no long turns)
    - No Narrator (two-character dialogue only)
    """
    if isinstance(raw_input, dict):
        script_data = raw_input
    else:
        try:
            script_data = json.loads(raw_input)
        except Exception as e:
            print(f"  ❌ Structural Failure: Output is not valid JSON. Error: {e}")
            return raw_input, False

    dialogue = script_data.get("dialogue", [])
    turn_count = len(dialogue)

    if turn_count < 14:
        print(f"  ❌ Retention Failure: Script has {turn_count} turns. Must be at least 14.")
        return script_data, False

    # Check speakers — only Emma and Liam allowed
    allowed_speakers = {"Emma", "Liam"}
    for turn in dialogue:
        speaker = turn.get("speaker", "")
        if speaker not in allowed_speakers:
            print(f"  ⚠️ Speaker Warning: '{speaker}' is not Emma or Liam. Mapping to Emma.")
            turn["speaker"] = "Emma"

    # Check for excessively long sentences (A1-A2 should be short)
    long_sentences = []
    for turn in dialogue:
        text = turn.get("text", "")
        word_count = len(text.split())
        if word_count > 20:
            long_sentences.append((turn.get("turn_number"), word_count))
    if long_sentences:
        print(f"  ⚠️ Sentence Warning: {len(long_sentences)} turn(s) exceed 20 words (A1-A2 should be 5-12 words).")

    # Check for pause markers
    has_pause = any(
        PAUSE_CUE_RE.match(turn.get("text", "")) is not None
        for turn in dialogue
    )
    if not has_pause:
        print("  ⚠️ Interactive Warning: No [PAUSE] token found. Adding one may help listener engagement.")

    print(f"  ✅ Slow English Script Verification Passed! Verified {turn_count} turns.")
    return script_data, True


# ─────────────────────────────────────────────
# SLOW ENGLISH POOL — idiom-focused (legacy)
# ─────────────────────────────────────────────

SLOW_IDIOM_POOL = [
    "Break a leg",
    "Hit the nail on the head",
    "Bite the bullet",
    "Spill the beans",
    "Under the weather",
    "Cost an arm and a leg",
    "Beat around the bush",
    "Burning the midnight oil",
    "Let the cat out of the bag",
    "Once in a blue moon",
    "Piece of cake",
    "Hit the sack",
    "Kick the bucket",
    "The ball is in your court",
    "Better late than never",
    "Don't judge a book by its cover",
    "Bite off more than you can chew",
    "Barking up the wrong tree",
    "Caught between a rock and a hard place",
    "Hit the road",
    "Get out of hand",
    "Pull someone's leg",
    "On the fence",
    "Under the table",
    "Go back to the drawing board",
    "Cut corners",
    "Jump on the bandwagon",
    "Miss the boat",
    "Bite the hand that feeds you",
    "Add fuel to the fire",
    "Back to square one",
    "Blow off steam",
    "Burn bridges",
    "Catch someone red-handed",
    "Cold turkey",
    "Cut to the chase",
    "Devil's advocate",
    "Don't cry over spilled milk",
    "Drop the ball",
    "Every cloud has a silver lining",
    "Face the music",
    "Get cold feet",
    "Give someone the benefit of the doubt",
    "Go the extra mile",
    "Hit the books",
    "In hot water",
    "It takes two to tango",
    "Kill two birds with one stone",
    "Let sleeping dogs lie",
    "On thin ice",
]


def generate_english_shorts_script(topic=None):

    if not topic:
        topic = generate_dynamic_topic(is_challenge=False, topic_type="shorts")
    else:
        # Check if manual topic is already published
        if is_already_published(topic, "shorts"):
            print(f"\n  [WARNING] Manual shorts topic '{topic}' was found in 'shorts' history.")

    # History injection
    topics_data = get_published_topics()
    recent = topics_data.get("shorts", [])[-50:]
    avoid_instruction = f"\nAvoid welcoming to channel, and avoid repeating concepts or phrasing from these recent shorts:\n{json.dumps(recent, indent=2)}" if recent else ""

    print(f"\nSelected Shorts topic: {topic}")
    prompt = f"""
You are writing a short, snappy English learning podcast script for a high CTR YouTube Short on 'EnglishVibesHub' (@EnglishVibesHub-s6w).
TOPIC: {topic}
{avoid_instruction}
{ENGLISH_METADATA_RULES}

CRITICAL RULES:
- Output ONLY valid JSON
- The `dialogue` array MUST contain around 8-12 turns in total (25-40 seconds of speaking).
- Hosts must be Emma (energetic, helpful) and Liam (curious, friendly).
- Teach 1 or 2 specific phrasal verbs, idioms, or useful expressions related to the topic.
- Use searchable keywords in the title: e.g., "English in 60 Seconds" or "Speak English Like a Native".
- Do NOT use mid-episode sign-offs or long pauses or one saying it was really helpful etc.
- The script must start with a strong hook and end with a phrase that seamlessly loops back to the beginning.
- The final turn should include a quick call to action that encourages re-watching (e.g., "Did you catch that? Let's try another one...").

STYLE:
- Fast-paced, punchy, conversational, and highly engaging.
- Perfect for vertical YouTube Shorts.
- No intro, no outro. The video should feel like it starts mid-conversation and loops perfectly.
- Write for the ear: exclamation marks for energy ("Oh, definitely!"), question marks for hooks ("But wait — is that actually correct?"), em-dashes for interruptions.
- Each line should feel like a natural reaction, not a scripted line.

JSON SCHEMA:
{{
  "title": "string (High-CTR Short title under 70 chars. Use varied formulas: question, 'Stop Saying X', 'X vs Y', number list, mistake hook, curiosity gap. Rotate from what you used last time.)",
  "title_options": ["string"],
  "description": "string (Follow METADATA RULES template. First 2 lines MUST use 'Natural English' and 'Speak like a native'. Place comment question in lines 3-5. Include subscribe CTA, playlist placeholder, #Shorts, and hashtags mirroring 'tags')",
  "pinned_comment": "string (An engaging question to pin in the comments section)",
  "tags": ["string (Provide 5-8 SEO-focused English learning and topic-specific tags)"],
  "theme": "string (short topic label for storyboard)",
  "visual_keywords": ["string (legacy fallback: 5-8 visual search words)"],
  "video_format": "shorts",
  "dialogue": [
    {{
      "turn_number": 0,
      "speaker": "Emma or Liam",
      "text": "string (the spoken text)"
    }}
  ]
}}
"""
    script_data = call_groq_json(prompt)
    # Preprocess to separate mixed pause markers
    script_data = separate_mixed_pause_turns(script_data)
    script_data.setdefault("video_format", "shorts")
    theme = script_data.get("theme") or script_data.get("title", "")
    script_data["description"] = finalize_english_description(script_data.get("description", ""), theme=theme, is_shorts=True, format="shorts")

    if not script_data.get("title"):
        title_options = script_data.get("title_options") or []
        if title_options:
            script_data["title"] = title_options[0]

    # Update pinned comment with channel CTA
    script_data = update_pinned_comment_with_channel_cta(script_data)

    return attach_storyboard_to_script(script_data, portrait=True)

def generate_english_quiz_shorts_script(topic: str = None) -> dict:
    """Strategy 1: Generate a MCQ Quiz Short."""
    topics_data = get_published_topics()
    published_quizzes = topics_data.get("quiz", [])

    if not topic:
        topic = generate_dynamic_topic(is_challenge=False, topic_type="quiz")
    elif is_already_published(topic, "quiz"):
        print(f"\n  [WARNING] Manual quiz topic '{topic}' was found in 'quiz' history.")

    print(f"\nSelected Quiz topic: {topic}")

    recent = published_quizzes[-50:] if published_quizzes else []
    avoid_instruction = ""
    if recent:
        avoid_instruction = (
            f"\nAvoid welcoming to channel, and avoid repeating or using the same distractors from these recent quizzes:\n"
            + json.dumps(recent, indent=2)
        )
    
    prompt = f"""
    You are an expert short-form scriptwriter. Generate a high-retention, 25-second YouTube Shorts English quiz loop between Emma and Liam for 'EnglishVibesHub' (@EnglishVibesHub-s6w).
    TOPIC: {topic}
    {avoid_instruction}
    {ENGLISH_METADATA_RULES}
    
    HIGH CTR & SEARCH-FOCUSED TITLE STRATEGY:
    High-CTR, curiosity-based title using benefit-focused hooks like 'Master This Skill', 'Complete Guide To...', 'Essential Phrases', or 'The Secret To...'. e.g., 'Master Better Responses: Beyond I'm Fine') along with searchable keywords: "English Practice for Beginners", "Easy English Listening", "English Quiz" etc.

    TIME ALLOCATION RULES:
    - [0-3s] Hook: Emma introduces the quiz question clearly based on the topic.
    - [3-13s] Sequential Options: Liam presents Options A, B, and C sequentially. Allocate exactly 3.3 seconds per option (Liam should have 3 separate dialogue turns for these).
    - [13-18s] Context Hint: Liam provides an educational example sentence or hint.
    - [18-20s] Thinking Pause: Insert a [PAUSE 2 SECONDS] turn to let viewers commit to their answer before the reveal.
    - [20-25s] Answer Reveal & Perfect Loop CTA: Emma reveals the answer and ends with a phrase that seamlessly loops back to the hook (e.g., "Let's try another one..."). Do NOT repeat the original question.

    PACING:
    The pacing must allow English learners time to read, but remain engaging enough to prevent swipe-aways.
    - Emma's hook should feel like a genuine question, not a script reading — use "Wait, do you know what ___ means?"
    - Liam's options should sound like natural suggestions, not a list being read aloud.

    LEVERAGE COMMENTS: Generate a 'pinned_comment' question to trigger algorithmic signals.

    JSON SCHEMA:
    {{
      "title": "string (High-CTR, searchable title under 70 chars, e.g., 'English Quiz: Master This Skill!')",
      "description": "string (Follow METADATA RULES template. First 2 lines MUST use 'Natural English' and 'Speak like a native'. Place comment question in lines 3-5. Include subscribe CTA, playlist placeholder, #Shorts, #EnglishQuiz, and hashtags mirroring 'tags')",
      "pinned_comment": "string (Engaging specific question for the comments section)",
      "tags": ["string (Provide 5-8 SEO-focused tags)"],
      "correct_answer": "string",
      "theme": "string (short topic label for storyboard, e.g. 'Quiz - Phrasal Verbs')",
      "visual_keywords": ["string (legacy fallback: 5-8 visual search words)"],
      "dialogue": [
        {{ "turn_number": 0, "speaker": "Emma", "text": "..." }},
        {{ "turn_number": 1, "speaker": "Liam", "text": "..." }}
      ]
    }}
    """
    script_data = call_groq_json(prompt)
    # Preprocess to separate mixed pause markers
    script_data = separate_mixed_pause_turns(script_data)
    script_data["video_format"] = "shorts_quiz"
    theme = script_data.get("theme") or script_data.get("title", "")
    script_data["description"] = finalize_english_description(
        script_data.get("description", ""), is_quiz=True, format="quiz", theme=theme
    )

    # Update pinned comment with channel CTA
    script_data = update_pinned_comment_with_channel_cta(script_data)

    return attach_storyboard_to_script(script_data, portrait=True)


# ─── PODCAST PIPELINE ─────────────────────────────────────────────────────────

def _extract_podcast_story_context(dialogue: list) -> str:
    """Extract a compact story-context summary from dialogue for the storyboard prompt.

    Parses the dialogue to identify the story setting, characters, and a text excerpt
    so the storyboard Groq call has enough context to generate accurate visuals
    instead of hallucinating unrelated locations.
    """
    story_speakers = {
        "Caller", "Caller_Male", "StoryActor1", "StoryActor2",
        "StoryActor1_Female", "StoryActor2_Male",
        "StoryActor1_AltMale", "StoryActor2_AltFemale",
    }
    story_lines = []
    for t in dialogue:
        if t.get("speaker") in story_speakers:
            story_lines.append(t.get("text", ""))
    full_story = " ".join(story_lines)

    if not full_story.strip():
        return ""

    # Extract setting/location cues from story text (use word boundaries to avoid
    # false positives like "bus" matching inside "business")
    location_keywords = {
        "office": "office/workplace", "meeting": "meeting room",
        "zoom": "video call/virtual meeting",
        "presentation": "presentation/meeting", "client": "client meeting",
        "interview": "interview setting", "restaurant": "restaurant",
        "cafe": "cafe", "coffee": "cafe", "bar": "bar/pub",
        "hotel": "hotel", "airport": "airport", "hospital": "hospital",
        "doctor": "medical office", "clinic": "clinic",
        "school": "school", "classroom": "classroom", "university": "university",
        "library": "library", "street": "street/outdoors", "park": "park",
        "gym": "gym", "store": "store/shop", "shop": "store/shop",
        "mall": "shopping mall", "supermarket": "grocery store",
        "home": "home", "house": "house", "apartment": "apartment",
        "kitchen": "kitchen", "bedroom": "bedroom",
        "car": "car/vehicle", "bus": "bus", "train": "train",
        "beach": "beach", "mountain": "mountain",
        "wedding": "wedding", "party": "party", "concert": "concert",
        "theater": "theater",
    }
    detected = set()
    story_lower = full_story.lower()
    for kw, label in location_keywords.items():
        if re.search(r'\b' + re.escape(kw) + r'\b', story_lower):
            detected.add(label)

    # Identify story characters
    characters = []
    for t in dialogue:
        sp = t.get("speaker", "")
        if sp.startswith("StoryActor") and sp not in characters:
            characters.append(sp)

    setting = ", ".join(sorted(detected)) if detected else "unspecified setting"
    chars = ", ".join(characters) if characters else "Caller only"
    word_count = len(full_story.split())

    return (
        f"STORY SETTING: {setting}. "
        f"CHARACTERS IN STORY: {chars}. "
        f"STORY LENGTH: ~{word_count} words across {len(story_lines)} dialogue turns. "
        f"STORY EXCERPT (first 500 chars): {full_story[:500]}"
    )


def _fix_podcast_scene_alignment(scenes: list, dialogue: list) -> list:
    """Validate and fix scene turn ranges using speaker identity for the podcast structure.

    Uses Groq's start_turn/end_turn as hints, then clamps each scene to the correct
    stage range based on its label. If scenes within a stage overlap, shifts later ones
    to start after the previous one ends. Preserves Groq's intent while fixing errors.
    """
    if not scenes or not dialogue:
        return scenes

    num_turns = len(dialogue)
    host_speakers = {"Emma", "Liam"}
    story_speakers = {"StoryActor1", "StoryActor2", "StoryActor1_Female", "StoryActor2_Male",
                      "StoryActor1_AltMale", "StoryActor2_AltFemale"}

    # Build speaker-type index: 0=hook/unknown, 1=host, 2=story, 3=caller
    speaker_type = []
    for t in dialogue:
        sp = t.get("speaker", "")
        if sp in host_speakers:
            speaker_type.append(1)
        elif sp in story_speakers:
            speaker_type.append(2)
        elif sp in ("Caller", "Caller_Male"):
            speaker_type.append(3)
        else:
            speaker_type.append(0)

    # Find stage boundaries from speaker types
    first_host_turn = next((i for i, st in enumerate(speaker_type) if st == 1), None)

    # First StoryActor turn after the first host turn = story start
    story_start = None
    if first_host_turn is not None:
        for i in range(first_host_turn, num_turns):
            if speaker_type[i] == 2:
                story_start = i
                break

    # Last StoryActor turn = story end
    last_story_turn = None
    for i in range(num_turns - 1, -1, -1):
        if speaker_type[i] == 2:
            last_story_turn = i
            break

    # First Caller turn between first host turn and story start = caller setup start
    caller_setup_start = None
    if first_host_turn is not None and story_start is not None:
        for i in range(first_host_turn, story_start):
            if speaker_type[i] == 3:
                caller_setup_start = i
                break

    # Studio intro end: last host turn before caller setup (or before story if no caller setup)
    studio_intro_end = None
    if first_host_turn is not None:
        intro_end_bound = caller_setup_start if caller_setup_start is not None else story_start
        if intro_end_bound is not None:
            for i in range(intro_end_bound - 1, first_host_turn - 1, -1):
                if speaker_type[i] == 1:
                    studio_intro_end = i
                    break
            if studio_intro_end is None:
                studio_intro_end = first_host_turn

    # Caller setup end: turn before story start
    caller_setup_end = story_start - 1 if story_start is not None else None

    # First Caller turn after story = back-to-studio starts with host transition
    caller_after_story = None
    if last_story_turn is not None:
        for i in range(last_story_turn + 1, num_turns):
            if speaker_type[i] == 3:
                caller_after_story = i
                break

    # Back-to-studio: host transition turn + caller reflection turns
    back_to_studio_start = None
    back_to_studio_end = None
    if last_story_turn is not None:
        # Starts at first host or caller turn after story
        for i in range(last_story_turn + 1, num_turns):
            if speaker_type[i] in (1, 3):
                back_to_studio_start = i
                break
        # Ends at last caller turn before host analysis
        if back_to_studio_start is not None:
            for i in range(back_to_studio_start, num_turns):
                if speaker_type[i] == 3:
                    back_to_studio_end = i
            # Extend to include host transition if host starts back-to-studio
            if back_to_studio_start is not None and speaker_type[back_to_studio_start] == 1:
                # Host started back-to-studio, find where caller ends
                for i in range(back_to_studio_start + 1, num_turns):
                    if speaker_type[i] == 3:
                        back_to_studio_end = i

    # First Host turn after back-to-studio = host analysis start
    host_after_caller = None
    search_start = (back_to_studio_end + 1) if back_to_studio_end is not None else (last_story_turn + 1 if last_story_turn is not None else 0)
    for i in range(search_start, num_turns):
        if speaker_type[i] == 1:
            host_after_caller = i
            break

    # If no story actors found, return scenes unchanged
    if first_host_turn is None or last_story_turn is None or story_start is None:
        return scenes

    # Define valid turn ranges for each stage (inclusive)
    hook_end = max(0, first_host_turn - 1)
    story_end = last_story_turn
    host_analysis_start = host_after_caller

    # DEBUG: Log computed stage boundaries
    print(f"  [podcast_align] Stage boundaries computed:")
    print(f"    hook_end: {hook_end}")
    print(f"    first_host_turn: {first_host_turn}")
    print(f"    studio_intro_end: {studio_intro_end}")
    print(f"    caller_setup_start: {caller_setup_start}")
    print(f"    caller_setup_end: {caller_setup_end}")
    print(f"    story_start: {story_start}")
    print(f"    story_end: {story_end}")
    print(f"    back_to_studio_start: {back_to_studio_start}")
    print(f"    back_to_studio_end: {back_to_studio_end}")
    print(f"    host_analysis_start: {host_analysis_start}")
    # Host analysis end = quiz start
    # Search for the first turn after host analysis that contains quiz-related keywords
    pause_idx = None
    for i in range(num_turns - 1, -1, -1):
        if "[PAUSE" in dialogue[i].get("text", "").upper():
            pause_idx = i
            break
    # Find quiz start: first turn with "quiz", "test", "challenge", or "which" after host analysis
    quiz_start = None
    if host_analysis_start is not None:
        for i in range(host_analysis_start + 2, num_turns):  # +2 to ensure at least 2 turns of analysis
            text_lower = dialogue[i].get("text", "").lower()
            if any(kw in text_lower for kw in ["quiz", "test", "challenge", "which "]):
                quiz_start = i
                break
    # Fallback: use pause_idx heuristic
    if quiz_start is None and pause_idx is not None:
        quiz_start = max(pause_idx - 2, (host_analysis_start + 2) if host_analysis_start else 0)
    if quiz_start is None and host_analysis_start is not None:
        quiz_start = host_analysis_start + 8

    # Map stage labels to valid ranges
    def label_to_stage(label: str) -> str:
        label = label.lower()
        if "hook" in label:
            return "hook"
        if "studio intro" in label or "radio studio" in label:
            return "studio_intro"
        if "caller story setup" in label or "caller setup" in label:
            return "caller_setup"
        if "back to studio" in label:
            return "back_to_studio"
        if "quiz" in label:
            return "quiz_wrap"
        if "wrap" in label:
            return "quiz_wrap"
        if "summary" in label:
            return "summary"
        # Analysis labels: "host analysis", "analysis:", "analysis —", etc.
        if "analysis" in label or "analyse" in label:
            return "host_analysis"
        # Story labels: "caller story", "flashback", "story part", etc.
        if "caller story" in label or "caller part" in label:
            return "story"
        if "flashback" in label:
            return "story"
        if "story" in label:
            return "story"
        return "unknown"

    def stage_range(stage: str):
        """Return (start, end) inclusive turn range for a stage."""
        if stage == "hook":
            return (0, hook_end)
        if stage == "studio_intro":
            if studio_intro_end is not None:
                return (first_host_turn, studio_intro_end)
            return None
        if stage == "caller_setup":
            if caller_setup_start is not None and caller_setup_end is not None:
                return (caller_setup_start, caller_setup_end)
            return None
        if stage == "story":
            return (story_start, story_end)
        if stage == "back_to_studio":
            if back_to_studio_start is not None and back_to_studio_end is not None:
                return (back_to_studio_start, back_to_studio_end)
            return None
        if stage == "host_analysis":
            if host_analysis_start is not None:
                return (host_analysis_start, max(host_analysis_start, quiz_start - 1))
            return None
        if stage == "quiz_wrap":
            if host_analysis_start is not None:
                return (quiz_start, num_turns - 1)
            return None
        if stage == "summary":
            return (max(0, num_turns - 2), num_turns - 1)
        return None

    # ── Boundary-first rebuild ──────────────────────────────────────────────
    # Discard Groq's broken turn ranges entirely. Build scenes directly from
    # computed stage boundaries, using Groq's labels/images as hints.
    # Result: max 4 scenes — Hook, Studio (pre-story), Flashback, Studio (post-story)

    # 1) Hook scene
    hook_scene = {
        "scene_id": 1,
        "scene_label": "Story Hook",
        "image_filename": "scene_hook.png",
        "visual_prompt": "",
        "start_turn": 0,
        "end_turn": hook_end,
    }
    # Copy Groq's hook visual_prompt if available
    for s in scenes:
        if "hook" in s.get("scene_label", "").lower():
            hook_scene["visual_prompt"] = s.get("visual_prompt", "")
            hook_scene["image_filename"] = s.get("image_filename", "scene_hook.png")
            break

    # 2) Pre-story studio scene (Studio Intro + Caller Setup merged)
    studio_pre_start = first_host_turn
    studio_pre_end = caller_setup_end if caller_setup_end is not None else (story_start - 1 if story_start else num_turns - 1)
    studio_pre_scene = {
        "scene_id": 2,
        "scene_label": "Radio Studio",
        "image_filename": "podcast_host.png",
        "visual_prompt": "Two podcast hosts, Emma and Liam, sitting in a modern radio station recording a podcast. Emma has brown hair in a neat ponytail. Liam has short blonde hair. Soft professional lighting, 3D Pixar style.",
        "start_turn": studio_pre_start,
        "end_turn": studio_pre_end,
    }

    # 3) Flashback scenes (use Groq's story scenes with correct range)
    story_scenes_groq = [s for s in scenes if label_to_stage(s.get("scene_label", "")) == "story"]
    story_range = (story_start, story_end)
    flashback_scenes = []
    if story_scenes_groq and story_start is not None and story_end is not None:
        story_span = story_end - story_start + 1
        n_story = len(story_scenes_groq)
        for si, gs in enumerate(story_scenes_groq):
            # Divide the story range evenly among Groq's story scenes
            chunk_start = story_start + (si * story_span // n_story)
            chunk_end = story_start + ((si + 1) * story_span // n_story) - 1
            if si == n_story - 1:
                chunk_end = story_end  # last scene gets the remainder
            flashback_scenes.append({
                "scene_id": 3 + si,
                "scene_label": gs.get("scene_label", f"Story Part {si + 1}"),
                "image_filename": gs.get("image_filename", f"scene_story{si + 1}.png"),
                "visual_prompt": gs.get("visual_prompt", ""),
                "start_turn": chunk_start,
                "end_turn": chunk_end,
            })
    elif story_start is not None and story_end is not None:
        # No Groq story scenes — create one generic flashback scene
        flashback_scenes.append({
            "scene_id": 3,
            "scene_label": "Caller Story",
            "image_filename": "scene_story1.png",
            "visual_prompt": "",
            "start_turn": story_start,
            "end_turn": story_end,
        })

    # 4) Post-story studio scene (Back to Studio + Analysis + Quiz merged)
    studio_post_start = back_to_studio_start if back_to_studio_start is not None else (last_story_turn + 1 if last_story_turn is not None else 0)
    studio_post_scene = {
        "scene_id": 3 + len(flashback_scenes),
        "scene_label": "Back to Studio",
        "image_filename": "podcast_host.png",
        "visual_prompt": "Two podcast hosts, Emma and Liam, sitting in a modern radio station recording a podcast. Emma has brown hair in a neat ponytail. Liam has short blonde hair. Soft professional lighting, 3D Pixar style.",
        "start_turn": studio_post_start,
        "end_turn": num_turns - 1,
    }

    corrected = [hook_scene, studio_pre_scene] + flashback_scenes + [studio_post_scene]
    print(f"  [podcast_align] Rebuilt {len(corrected)} scenes from stage boundaries")

    # Remove empty scenes (start > end)
    corrected = [s for s in corrected if s.get("start_turn", 0) <= s.get("end_turn", 0)]

    # Ensure first scene starts at 0
    if corrected and corrected[0].get("start_turn", 0) != 0:
        corrected[0]["start_turn"] = 0
    # Ensure last scene ends at final turn
    if corrected and corrected[-1].get("end_turn", 0) != num_turns - 1:
        corrected[-1]["end_turn"] = num_turns - 1

    print(f"  [podcast_align] Final scene coverage:")
    for i, scene in enumerate(corrected):
        print(f"    Scene {i+1} ({scene.get('scene_label', '?')}): turns {scene['start_turn']}-{scene['end_turn']}")

    return corrected


def generate_podcast_storyboard(script: dict, topic: str = "") -> dict:
    """Post-dialogue Groq call: group dialogue into Pixar-style visual scenes with podcast host switching."""
    dialogue = script.get("dialogue", [])
    if not dialogue:
        script.setdefault("scenes", [])
        return script

    turns_summary = "\n".join(
        f"{i}: [{line.get('speaker', '?')}] {line.get('text', '')[:150]}"
        for i, line in enumerate(dialogue[:120])
    )
    style_suffix = ENGLISH_STORYBOARD_STYLE_SUFFIX_LANDSCAPE
    theme = script.get("theme") or script.get("title", "English Lesson")
    num_turns = len(dialogue)

    story_context = _extract_podcast_story_context(dialogue)
    topic_context = f"\n\nTOPIC: {topic}" if topic else ""
    story_context_block = f"\n\n{story_context}" if story_context else ""
    
    prompt = f"""You are an expert AI storyboard director for a 3D Pixar-style YouTube channel.
Analyze the input script. Group the dialogue turns into sequence of scenes.{topic_context}{story_context_block}

The podcast follows this 7-stage structure:
1. Story Hook (turns 0-1) - 2-line teaser, high tension
2. Radio Studio Intro - Emma & Liam welcome listeners and introduce caller
3. Caller Story Setup - Caller talks to hosts, briefly explains what happened
4. Caller Story - Full story flashback acted out through dialogue
5. Back to Studio - Caller reflects with lingering confusion
6. Host Analysis - Emma & Liam explain correct English usage
7. Quiz & Wrap-up - Interactive challenge and episode conclusion

Emma and Liam are radio show hosts sitting in a modern radio station.
Host segments (Radio Studio Intro, Caller Story Setup, Host Analysis, Quiz & Wrap-up) should use the podcast_host.png image.
Story segments (Story Hook, Caller Story, Back to Studio) should use unique Pixar-style scene images.

CRITICAL RULES:
1. For host segments (Emma/Liam as radio hosts in studio), set "image_filename": "podcast_host.png" and "visual_prompt": "Two podcast hosts, Emma and Liam, sitting in a modern radio station recording a podcast. Emma has brown hair in a neat ponytail. Liam has short blonde hair. Soft professional lighting, 3D Pixar style."
2. For story segments (Story Hook, Caller Story), generate unique, highly descriptive Pixar-style prompts with filenames like "scene_2_crisis_moment.png" etc.
3. VISUAL-DIALOGUE ALIGNMENT: The "STORY EXCERPT" and "STORY SETTING" above describe the actual story. Every non-host scene's visual_prompt MUST depict settings, objects, and actions from that story. If the story mentions a Zoom call, show a person at a computer on a video call. If it mentions a restaurant, show a restaurant. NEVER use generic settings (high school, coffee shop, marketplace, hallway) unless the story EXPLICITLY mentions them. DO NOT invent settings or character appearances not described in the story excerpt.
4. The style must ALWAYS be: "{style_suffix}" for story scenes.
5. Create 10-15 scenes total with appropriate labels matching the 7 stages: "Story Hook", "Radio Studio Intro", "Caller Story Setup", "Caller Story", "Back to Studio", "Host Analysis", "Quiz & Wrap-up". Ensure scenes sequentially cover all turns from 0 to {num_turns - 1}. Break up longer segments into multiple scenes for visual variety.
6. ONLY IF the episode explicitly teaches idioms or phrasal verbs (e.g. "kick the bucket", "break a leg"), add a final scene with "scene_label": "Summary Card". Set "start_turn" to the last host analysis turn and "end_turn" to the final turn. Use "scene_summary.png" and a visual_prompt showing an atmospheric background matching the story setting (no characters). If the episode does NOT teach idioms/phrasal verbs, do NOT add a Summary Card scene.

Output ONLY valid JSON with this schema:
{{
  "theme": "string",
  "scenes": [
    {{
      "scene_id": 1,
      "scene_label": "string (short chapter label for YouTube timeline)",
      "image_filename": "podcast_host.png",
      "visual_prompt": "Two podcast hosts, Emma and Liam, sitting in a modern radio station recording a podcast. Emma has brown hair in a neat ponytail. Liam has short blonde hair. Soft professional lighting, 3D Pixar style.",
      "start_turn": 0,
      "end_turn": 2
    }}
  ]
}}
"""
    try:
        res = call_groq_json(prompt)
        scenes = res.get("scenes", [])
        if not isinstance(scenes, list):
            scenes = []
        for scene in scenes:
            if scene.get("image_filename") == "podcast_host.png":
                continue
            vp = str(scene.get("visual_prompt", "")).strip()
            # Remove any narrator, caption, or text references
            vp = re.sub(r"\bnarrator'?s?\b[^,.]*", '', vp, flags=re.IGNORECASE)
            vp = re.sub(r'\s+,', ',', vp)
            vp = re.sub(r'\s{2,}', ' ', vp)
            vp = re.sub(r',\s*\.', '.', vp)
            vp = vp.strip()
            if vp and style_suffix.lower() not in vp.lower():
                scene["visual_prompt"] = f"{vp.rstrip('.')} {style_suffix}"
            elif vp:
                scene["visual_prompt"] = vp
        script["theme"] = res.get("theme") or theme
        script["scenes"] = align_scenes_to_turns(scenes, dialogue)
        script["scenes"] = _fix_podcast_scene_alignment(script["scenes"], dialogue)
        print(f"  Storyboard: {len(script['scenes'])} scene(s) generated")
    except Exception as exc:
        print(f"  Storyboard generation skipped (Groq error): {exc}")
        script.setdefault("scenes", [])
    return script


def generate_english_podcast_script(topic=None):
    """Generate a podcast script with Emma & Liam as hosts and dynamic scenes."""
    if not topic:
        topic = generate_dynamic_topic(is_challenge=False, topic_type="podcast")
    else:
        if is_already_published(topic, "podcast"):
            print(f"\n  [WARNING] Manual topic '{topic}' was found in 'podcast' history.")

    topics_data = get_published_topics()
    recent = topics_data.get("podcast", [])[-50:]
    avoid_instruction = f"\nAvoid repeating examples, idioms, or stories used in these recent episodes:\n{json.dumps(recent, indent=2)}" if recent else ""

    print(f"\nSelected topic: {topic}")
    print("Generating podcast storytelling script...")

    prompt = f"""
You are an elite showrunner for EnglishVibesHub (@EnglishVibesHub-s6w). Write an English audio-story script for the "English Vibes Podcast".

TOPIC: {topic}
{avoid_instruction}

{PODCAST_METADATA_RULES.replace('{playlist_url}', '{{playlist_url}}')}

FORMAT: Radio podcast, 50+ dialogue turns (doubled for longer, more comprehensive content), 7 stages in this EXACT order:

1. HOOK (2 turns): Caller in media res — ONE punchy 1-2 sentence line of high tension. StoryActor gives ONE short direct reaction (not narrated). Then STOP — cut to studio.
2. STUDIO INTRO (2-3 turns): Emma welcomes listeners, Liam introduces topic, Emma introduces caller.
3. CALLER STORY SETUP (2-3 turns): Caller tells Emma & Liam about a confusing English situation they witnessed involving a friend or colleague. Use 3rd-person framing: "my friend said...", "my colleague told me...", "someone at work said...". Hosts react naturally. This sets up the story BEFORE the flashback. Then Liam or Emma hands off.
4. FULL STORY (12-16 turns): A flashback scene. StoryActor1 and StoryActor2 ARE the characters — they speak DIRECTLY to each other as themselves. NO narration, NO "he said/she said", NO body language descriptions like "I raised an eyebrow and said". Just the spoken line. Example WRONG: "He leaned back and said, 'We can discuss this later.'" Example RIGHT: "We can discuss this later." The Caller does NOT appear in this stage. The story is told entirely through the characters' own dialogue. Build: setup → tension → complication → climax. This is the ONLY place the full story is told. Extended to 12-16 turns for more detailed storytelling and cultural context.
5. BACK TO STUDIO (2-3 turns): Host asks a follow-up. Caller still doesn't understand what went wrong with their friend's/colleague's English. References the character by role ("my friend", "my coworker"), not as themselves.
6. HOST ANALYSIS (16-20 turns): Emma/Liam react, explain the mistake, teach correct usage with MORE detailed examples and cultural context. Include multiple practice scenarios and deeper explanations. Include one quiz with this EXACT turn sequence:
   (a) Host verbally cues the challenge (e.g., "Quick challenge — which one is correct?")
   (b) Emma or Liam on their own turn: "Option A: [text]" (speaker field must be "Emma" or "Liam")
   (c) Emma or Liam on their own turn: "Option B: [text]" (speaker field must be "Emma" or "Liam")
   (d) Emma or Liam on their own turn: "Option C: [text]" (speaker field must be "Emma" or "Liam")
   (e) A SEPARATE turn with speaker "Emma" or "Liam" and text exactly "[PAUSE 3 SECONDS]" (speaker field must be "Emma" or "Liam")
   (f) Host reveals the correct answer with brief explanation.
   NEVER put the pause before the options. NEVER combine multiple options into one turn. NEVER use "Option A", "Option B", "Option C", or "[PAUSE 3 SECONDS]" as speaker field values - always use character names.
7. WRAP-UP (2-3 turns): Host summarizes key takeaway. End conversationally.

VOICES:
- "Emma" & "Liam": Radio hosts. First-person. NEVER in Stage 4. Emma = energetic ("Oh, absolutely!"). Liam = curious ("Wait, so you're saying...?").
- "Caller" / "Caller_Male": Randomly alternate. Give realistic first name. 3rd-person narrator ("my friend said..."). Stages 1, 3, 5 only.
- "StoryActor1" & "StoryActor2": Characters IN the story. Direct spoken lines only — NO narration, NO body language. Use "_Female"/"_Male" variants as needed.
- "StoryActor1_Female", "StoryActor2_Male", "StoryActor1_AltMale", "StoryActor2_AltFemale": Alternative variants for StoryActor roles when needed.
- "Guest" (optional): Always female.

CRITICAL SPEAKER NAME RULES:
- ONLY use these EXACT speaker names: "Emma", "Liam", "Caller", "Caller_Male", "StoryActor1", "StoryActor2", "StoryActor1_Female", "StoryActor2_Male", "StoryActor1_AltMale", "StoryActor2_AltFemale", "Guest"
- NEVER invent custom speaker names like "Alex_Male", "Boss_Female", "Jenna", "Coworker", etc.
- If you need a male character in the story, use "StoryActor1" or "StoryActor2_Male"
- If you need a female character in the story, use "StoryActor2" or "StoryActor1_Female"
- The story characters are ALWAYS StoryActor1 and StoryActor2 (with gender variants as needed)

NATURAL EXPRESSION REQUIREMENTS:
- 2-3 phrasal verbs + 1-2 idioms used naturally. StoryActors speak like real people, not textbook examples.
- Caller uses 3rd-person framing ("my friend said..."). Emma/Liam highlight expressions in Stage 6.
- Include more detailed examples and cultural context throughout for comprehensive learning.

AVD-FOCUSED PACING (for longer content retention):
- Add engagement hooks every 30-45 seconds to prevent viewer drop-off
- Include interactive questions and challenges throughout the analysis section
- Maintain narrative momentum with cliffhangers between sections
- Use varied pacing to prevent monotony in the longer format
- Apply quiz-style engagement triggers (pinned comment questions, viewer participation)

ANTI-REPETITION RULE: In Stage 4 (Full Story), avoid repeating the same filler word or phrase (like "anyway", "so", "well") more than 2-3 times total. If a character overuses a transition word, it feels robotic and unnatural. Cut repetitive dialogue even if it reduces turn count.

SHARP HOST BACK-AND-FORTH: In Stage 6 (Host Analysis), Emma and Liam should NOT echo each other. Emma delivers the structural rules and framework, while Liam delivers explicit phrasing examples and concrete sentences. This creates a sharper teaching rhythm.

ACCELERATED TRANSITION: After Stage 4 (Full Story) ends, immediately transition into Stage 6 (Host Analysis) teaching the two definitive rules for the topic. Do not linger in Stage 5 (Back to Studio) with extended reflection - keep it to 2-3 turns maximum where Caller expresses lingering confusion, then move straight to the teaching.

RULES:
- 50+ total turns (doubled for longer, more comprehensive content). Hook=2, Studio=2-3, Caller Setup=2-3, Story=12-16, Back=2-3, Analysis=16-20, Wrap=2-3.
- StoryActors NEVER narrate. They speak directly as their characters. No "he said", "she whispered", "I nodded and replied" — just the line.
- Caller does NOT appear in Stage 4 (Full Story). Caller appears in Stages 1, 3, and 5.
- Caller uses 3rd-person framing: "my friend said..." not "I said...". The caller narrates someone else's story.
- Caller has a realistic first name. Hosts say "Hey Maya, thanks for calling in" — NOT "Hey Caller". But the JSON speaker key stays "Caller" or "Caller_Male".
- Emma/Liam never break into story dialogue.
- Story told ONCE in Stage 4. Hook is just a 2-line teaser. Caller Setup briefly sets up the story in studio.
- Output ONLY valid JSON.

JSON SCHEMA:
{{"title":"...","description":"...","pinned_comment":"...","tags":["..."],"dialogue":[{{"turn_number":1,"speaker":"Caller","text":"..."}},{{"turn_number":2,"speaker":"StoryActor1","text":"..."}}],"thumbnail_text":"...","thumbnail_concept":"...","theme":"2-5 words"}}

Dialogue MUST start with Caller (Hook), NOT Emma/Liam. After the story, Caller MUST return to studio for reflection before Host Analysis.
"""
    is_valid = False
    attempts = 0

    while not is_valid and attempts < 3:
        attempts += 1
        print(f"🔄 Generation Attempt {attempts}...")

        # Multi-part Groq call: Part 1 - Generate dialogue with higher turn count
        raw_script = call_groq_json(prompt)
        # Preprocess to separate mixed pause markers before validation
        raw_script = separate_mixed_pause_turns(raw_script)
        script, is_valid = validate_podcast_script(raw_script)

    if not is_valid:
        print("⚠️ Groq failed to generate a perfect script after 3 tries. Using last attempt.")

    # Post-process description and attach custom storyboard
    script = generate_podcast_storyboard(script, topic=topic)
    theme = script.get("theme") or script.get("title", "")
    if script.get("description"):
        script["description"] = finalize_english_description(
            script["description"],
            include_timeline=False,
            is_quiz=False,
            format="podcast",
            theme=theme,
        )
    return script

