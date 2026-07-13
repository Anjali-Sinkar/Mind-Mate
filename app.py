from datetime import datetime, date, timedelta
from io import BytesIO
import json
import os
import random
import secrets
import sqlite3
import tempfile
import urllib.error
import urllib.request
import urllib.parse
from pathlib import Path

from flask import Flask, jsonify, redirect, render_template, request, send_file, session, url_for
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
from werkzeug.security import check_password_hash, generate_password_hash
from dotenv import load_dotenv
from groq import Groq
from google import genai
from jokes_data import JOKES, get_all_jokes, get_random_joke
import wikipedia

BASE_DIR = Path(__file__).resolve().parent
TEMPLATE_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

load_dotenv(BASE_DIR / ".env")

DB_PATH = os.getenv("DATABASE_PATH", str(BASE_DIR / "mental_buddy.db"))

app = Flask(__name__, template_folder=str(TEMPLATE_DIR), static_folder=str(STATIC_DIR))
app.secret_key = os.getenv("FLASK_SECRET_KEY", "mental-health-buddy-secret-key-change-in-production")

# Care tools: single source of truth for templates (URLs are external streams; verify periodically)
BREATHING_MODES = [
    {"id": "stress", "label": "Stress relief", "inhale": 4, "hold": 2, "exhale": 4},
    {"id": "anxiety", "label": "Anxiety ease", "inhale": 4, "hold": 4, "exhale": 4},
    {"id": "sleep", "label": "Sleep wind-down", "inhale": 4, "hold": 2, "exhale": 6},
]

# Remote fallbacks: stable public MP3s that can be swapped easily.
# Override anytime by placing files in static/audio/ — see resolve_music_tracks().
MUSIC_TRACKS = [
    {
        "id": "background_music_soft_calm",
        "label": "Background Music Soft Calm",
        "subtitle": "A gentle, steady background track for calming the mind.",
        "url": "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-1.mp3",
    },
    {
        "id": "river_of_mindfulness",
        "label": "River of Mindfulness",
        "subtitle": "A soothing flowing soundscape to support mindfulness and breath.",
        "url": "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-2.mp3",
    },
    {
        "id": "inner_peace",
        "label": "Inner Peace",
        "subtitle": "A soft, reflective track for rest, reassurance, and focus.",
        "url": "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-3.mp3",
    },
]


def resolve_music_tracks():
    """Prefer local static/audio/<id>.mp3 when the file exists; else use MUSIC_TRACKS remote URL."""
    resolved = []
    for t in MUSIC_TRACKS:
        entry = dict(t)
        local_rel = f"audio/{t['id']}.mp3"
        local_path = STATIC_DIR / local_rel
        if local_path.is_file():
            entry["url"] = url_for("static", filename=local_rel)
        resolved.append(entry)
    return resolved

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "phi3")

# Initialize clients if keys exist
groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY and GROQ_API_KEY != "your_groq_api_key_here" else None
if GEMINI_API_KEY and GEMINI_API_KEY != "your_gemini_api_key_here":
    gemini_client = genai.Client(api_key=GEMINI_API_KEY)
else:
    gemini_client = None

# India mental health & emergency — verify locally; numbers may change over time.
# Helplines and Questions moved to DB


def resolve_db_path():
    """Use the configured DB path, falling back if the host has no writable disk mounted."""
    global DB_PATH
    configured_path = Path(DB_PATH)
    try:
        configured_path.parent.mkdir(parents=True, exist_ok=True)
        return str(configured_path)
    except OSError as exc:
        fallback_path = Path(tempfile.gettempdir()) / "mental_buddy.db"
        fallback_path.parent.mkdir(parents=True, exist_ok=True)
        print(f"Database path {configured_path} is not writable ({exc}); using {fallback_path}")
        DB_PATH = str(fallback_path)
        return DB_PATH


def get_db():
    conn = sqlite3.connect(resolve_db_path())
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            age INTEGER,
            email TEXT UNIQUE,
            password_hash TEXT,
            total_time_seconds INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS assessments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            emotion TEXT,
            stress_score INTEGER NOT NULL,
            anxiety_score INTEGER NOT NULL,
            depression_score INTEGER NOT NULL,
            primary_result TEXT NOT NULL,
            recommendation TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            user_message TEXT NOT NULL,
            bot_reply TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS usage_daily (
            user_id INTEGER NOT NULL,
            day TEXT NOT NULL,
            seconds INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (user_id, day),
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS tool_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            tool_name TEXT NOT NULL,
            count INTEGER NOT NULL DEFAULT 1,
            last_used_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS helplines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            number TEXT NOT NULL,
            note TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS assessment_questions (
            id TEXT PRIMARY KEY,
            text TEXT NOT NULL,
            type TEXT NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()
    seed_db()
    migrate_db()


def seed_db():
    conn = get_db()
    # Seed Helplines
    if not conn.execute("SELECT 1 FROM helplines LIMIT 1").fetchone():
        helplines = [
            ("Emergency (Police / Ambulance)", "112", "Single emergency number (India)"),
            ("Tele-MANAS (MoHFW)", "14416 / 1-800-891-4416", "National mental health helpline"),
            ("iCall (TISS)", "9152987821", "Mon–Sat, 8 am–10 pm"),
            ("Vandrevala Foundation", "9999666555", "24×7"),
            ("AASRA", "9820466726", "24×7"),
            ("Snehi", "9582208181", "Emotional support"),
            ("NIMHANS", "08046110007", "Mental health support"),
        ]
        conn.executemany("INSERT INTO helplines (name, number, note) VALUES (?, ?, ?)", helplines)

    # Seed Questions
    if not conn.execute("SELECT 1 FROM assessment_questions LIMIT 1").fetchone():
        questions = [
            ("stress_1", "How often did you feel tense today?", "stress"),
            ("stress_2", "How hard was it to relax your body?", "stress"),
            ("stress_3", "Did small tasks feel overwhelming?", "stress"),
            ("anxiety_1", "How often did your thoughts race?", "anxiety"),
            ("anxiety_2", "Did you feel restless or on edge?", "anxiety"),
            ("anxiety_3", "How often did you worry about the worst outcome?", "anxiety"),
            ("depression_1", "Did you feel low or empty today?", "depression"),
            ("depression_2", "How difficult was it to enjoy things?", "depression"),
            ("depression_3", "Did you feel withdrawn from people?", "depression"),
        ]
        conn.executemany("INSERT INTO assessment_questions (id, text, type) VALUES (?, ?, ?)", questions)
    
    conn.commit()
    conn.close()


def get_helplines():
    conn = get_db()
    rows = conn.execute("SELECT name, number, note FROM helplines").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_questions():
    conn = get_db()
    rows = conn.execute("SELECT id, text, type FROM assessment_questions").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def migrate_db():
    conn = get_db()
    cur = conn.execute("PRAGMA table_info(users)")
    cols = {row[1] for row in cur.fetchall()}
    if "email" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN email TEXT")
    if "password_hash" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN password_hash TEXT")
    if "total_time_seconds" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN total_time_seconds INTEGER NOT NULL DEFAULT 0")
    if "reset_token" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN reset_token TEXT")
    if "reset_expires_at" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN reset_expires_at TEXT")
    conn.commit()
    conn.close()


def get_time_context():
    hour = datetime.now().hour
    if 5 <= hour < 12:
        return "morning"
    if 12 <= hour < 18:
        return "daytime"
    if 18 <= hour < 23:
        return "evening"
    return "late_night"


def is_vulnerable_night_window():
    """2am–6am: research suggests elevated suicidal ideation risk; extra empathy."""
    h = datetime.now().hour
    return h >= 2 and h < 6


def crisis_reply():
    lines = [
        "I am really glad you told me this. You deserve immediate human support.",
        "If you might act on self-harm thoughts, call emergency services right now.",
        "India: Emergency 112 (national). Mental health: Tele-MANAS 14416 or 1-800-891-4416.",
        "Crisis lines: AASRA +91-9820466726, Vandrevala 9999666555, iCall 9152987821 (see Help page for full list).",
    ]
    return " ".join(lines)


def build_recommendation(primary, scores):
    prompt = (
        f"The user has completed a mental health assessment. "
        f"Primary concern: {primary}. "
        f"Scores: Stress={scores['stress']}, Anxiety={scores['anxiety']}, Depression={scores['depression']}. "
        "Provide a warm, supportive 2-3 sentence recommendation including one small actionable step."
    )
    rec = advanced_chat(prompt, None)
    if not rec:
        mapping = {
            "stress": "Focus on short breathing sets, hydration breaks, and light body movement every 2-3 hours.",
            "anxiety": "Use grounding techniques (5-4-3-2-1), slower exhale breathing, and reduce overstimulating content.",
            "depression": "Try small achievable actions, sunlight exposure, gentle music routines, and connect with one trusted person.",
        }
        return mapping.get(primary, "Continue mindful routines and reach out for support when needed.")
    return rec


def classify_assessment(scores, emotion):
    stress = scores["stress"]
    anxiety = scores["anxiety"]
    depression = scores["depression"]
    ranked = sorted(
        [("stress", stress), ("anxiety", anxiety), ("depression", depression)],
        key=lambda x: x[1],
        reverse=True,
    )
    primary = ranked[0][0]

    if emotion in ("sad", "angry", "fearful") and primary == "stress":
        primary = "anxiety"
    if emotion in ("sad", "neutral") and primary == "anxiety" and depression >= anxiety - 1:
        primary = "depression"
    return primary


def chat_system_prompt(user_name=None):
    """
    Builds the personality and behaviour for every AI model.
    This prompt is shared by Groq, Gemini and Ollama so MindMate
    always feels like the same companion.
    """

    time_context = get_time_context()
    vulnerable = is_vulnerable_night_window()

    helplines = get_helplines()
    helpline_text = ", ".join(
        f"{h['name']} ({h['number']})" for h in helplines
    )

    greeting_name = (
        f"The user's name is {user_name}. Use their name naturally once in a while, "
        "but never force it into every response."
        if user_name
        else "The user's name is unknown."
    )

    prompt = f"""
You are MindMate.
MindMate is NOT an AI assistant.
MindMate is NOT a therapist.
MindMate is NOT a motivational speaker.
MindMate is a calm, emotionally intelligent companion who helps people
feel heard, understood and a little lighter after every conversation.
--------------------------------------------------
PERSONALITY

Be
• warm
• calm
• patient
• emotionally mature
• conversational
• genuine
• encouraging

Never be
• robotic
• repetitive
• preachy
• overly motivational
• dramatic
• fake
• overly formal
--------------------------------------------------
MOST IMPORTANT RULE
Your first job is NOT solving problems.
Your first job is understanding people.
Conversation order should always be
1. Understand
2. Acknowledge
3. Explore
4. Support
5. Suggest (only if helpful)
Never jump straight into advice.
--------------------------------------------------
STYLE
Talk naturally.
Use contractions.
Examples
Instead of
"I understand."
say
"That makes sense."
Instead of
"I am here with you."
say
"I'm glad you told me."
Instead of
"You should"
say
"What do you think about..."
Avoid sounding scripted.
Every response should feel written specifically
for THIS user.
--------------------------------------------------
NEVER REPEAT
Avoid repeating phrases like
"I'm here for you."
"Take a deep breath."
"Take one step."
"You are valid."
"You are not alone."
Don't reuse the same sentence twice in one conversation.
--------------------------------------------------
MEMORY
Read previous conversation carefully.
Never restart the conversation.
Never pretend to forget.
If the user refers to
"it"
"that"
"this"
figure out what they mean from chat history.
--------------------------------------------------
PROGRESS
If the user made progress
celebrate it first.
Example
User:
"I fixed it."
Bad:
"What happened?"
Good:
"That's great! It sounds like you've made some real progress."
--------------------------------------------------
ADVICE
Don't give advice every message.
Sometimes people only want someone to listen.
--------------------------------------------------
QUESTIONS
Prefer natural questions like
"What do you think hurt the most?"
"What happened after that?"
"Has this been building for a while?"
instead of
"How are you feeling?"
--------------------------------------------------
EMOTIONS
If user is
happy
→ celebrate

sad
→ comfort

angry
→ stay calm

confused
→ clarify

lonely
→ stay present

stressed
→ reduce pressure

burnt out
→ encourage rest
--------------------------------------------------
HUMOUR
If user jokes
joke back gently.
--------------------------------------------------
LANGUAGE
Always answer in the SAME language
the user uses.
--------------------------------------------------
LENGTH
Keep every reply very short and gentle.
Usually 2 short paragraphs or 3-4 sentences total.
Do not exceed about 80-100 words.
If the user is upset, ask only one brief reflective question.
Longer only if user explicitly asks.
--------------------------------------------------
MEDICAL
Never diagnose.
Never prescribe medicine.
--------------------------------------------------
CRISIS
If user expresses
suicide
self harm
or immediate danger
respond calmly.
Encourage immediate human help.
Use these helplines
{helpline_text}
--------------------------------------------------
TIME
Current time period
{time_context}
If late night
don't mention the time every reply.
Only mention it naturally if it fits.
--------------------------------------------------
{greeting_name}
--------------------------------------------------
The user should leave every conversation feeling
heard
understood
less alone
and never judged.
"""
    return prompt.strip()

def trim_chat_reply(reply, max_words=90):
    """Keep chatbot replies short and readable by trimming oversize output."""
    if not reply:
        return reply
    cleaned = " ".join(reply.split())
    words = cleaned.split()
    if len(words) <= max_words:
        return cleaned.strip()
    trimmed = " ".join(words[:max_words]).strip()
    if not trimmed.endswith((".", "!", "?")):
        trimmed += "..."
    return trimmed


def chat_fallback_reply(message, lowered):
    """
    Natural fallback when all AI providers fail.
    Never sound repetitive or scripted.
    """
    risk_terms = [
        "suicide","kill myself","end my life",
        "self harm","self-harm",
        "want to die","better off dead",
        "no reason to live","can't go on"
    ]
    if any(t in lowered for t in risk_terms):
        return crisis_reply()
    # Greetings
    greetings = [
        "hi","hello","hey","hii","heyy","good morning",
        "good afternoon","good evening"
    ]
    if any(g == lowered for g in greetings):
        return random.choice([
            "Hey 😊 It's nice to hear from you. How has your day been going?",
            "Hi! I'm glad you dropped by. What's been on your mind today?",
            "Hello! What would you like to talk about today?",
            "Hey there! I'm all ears. What's going on?"
        ])

    # Thanks
    if any(x in lowered for x in ["thank","thanks","thank you"]):
        return random.choice([
            "You're always welcome. I'm glad you felt comfortable sharing that with me.",
            "I'm really happy our conversation helped even a little.",
            "Anytime. You don't have to carry everything alone."
        ])

    # Happy
    happy_words = [
        "happy","great","awesome","good news",
        "excited","promotion","passed","selected",
        "finally did it","i did it","success"
    ]

    if any(w in lowered for w in happy_words):
        return random.choice([
            "That's wonderful 😊 You sound genuinely happy, and I hope you take a moment to enjoy that feeling.",
            "I love hearing that! What do you think made the biggest difference?",
            "That's great news! You should be proud of yourself."
        ])

    # Stress

    stress = [
        "stress","stressed","pressure",
        "deadline","exam","workload",
        "busy","overwhelmed","panic"
    ]

    if any(w in lowered for w in stress):
        return random.choice([
            "That sounds like a lot to carry at once. What's feeling like the biggest source of pressure right now?",
            "When everything piles up together it can feel impossible. Which part feels the hardest today?",
            "You don't have to solve everything tonight. Let's untangle one thing at a time."
        ])

    # Anxiety
    anxiety = [
        "anxiety","anxious","worried",
        "scared","fear","nervous"
    ]

    if any(w in lowered for w in anxiety):
        return random.choice([
            "That sounds really unsettling. Has something specific triggered this feeling today?",
            "Anxiety can make even small things feel much bigger. What do you think has been sitting with you the most?",
            "I'm glad you mentioned it instead of keeping it inside. Want to tell me a little more?"
        ])

    # Sad

    sadness = [
        "sad","cry","crying",
        "depressed","lonely",
        "heartbroken","hurt"
    ]

    if any(w in lowered for w in sadness):
        return random.choice([
            "I'm sorry you're going through this. You don't have to rush yourself to feel okay.",
            "That sounds really painful. What happened, if you feel like talking about it?",
            "Sometimes saying it out loud makes it feel a little less heavy. I'm listening."
        ])

    # Anger

    anger = [
        "angry","hate","annoyed",
        "irritated","frustrated","mad"
    ]

    if any(w in lowered for w in anger):
        return random.choice([
            "It sounds like something really pushed you today. What happened?",
            "I can hear the frustration in what you're saying. Want to tell me more about it?",
            "That would leave a lot of people feeling upset too."
        ])

    # User is replying to previous message

    short_replies = [
        "yes","yeah","yup","no",
        "maybe","okay","ok","hmm",
        "hmmm","true","exactly"
    ]

    if lowered in short_replies:
        return random.choice([
            "Tell me a little more. I'm interested in hearing what's behind that.",
            "I'm with you. What happened after that?",
            "Take your time. There's no rush."
        ])

    # Default

    default = [

        "That makes sense. Can you tell me a little more about what's been going on?",

        "I'm glad you shared that with me. What do you think has been affecting you the most?",

        "I'm listening. Start wherever feels easiest.",

        "That sounds important. I'd like to understand it better if you're comfortable sharing.",

        "Thanks for trusting me with that. What has this experience been like for you?",

        "Let's figure this out together. What part feels the hardest right now?",

        "I'm here to listen without judging. Tell me whatever feels comfortable."

    ]

    return random.choice(default)


def get_chat_history(user_id, limit=12):
    conn = get_db()
    rows = conn.execute(
        "SELECT user_message, bot_reply FROM chat_logs WHERE user_id = ? ORDER BY id DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()
    conn.close()
    history = []
    for row in reversed(rows):
        history.append({"role": "user", "content": row["user_message"]})
        history.append({"role": "assistant", "content": row["bot_reply"]})
    return history

def groq_chat(user_message, history, user_name=None):
    if not groq_client:
        return None

    try:

        messages = [
            {
                "role": "system",
                "content": chat_system_prompt(user_name)
            }
        ]

        messages.extend(history)

        messages.append(
            {
                "role": "user",
                "content": user_message
            }
        )

        completion = groq_client.chat.completions.create(
            model=GROQ_MODEL,
            messages=messages,
            temperature=0.5,
            max_tokens=160,
            top_p=0.9,
            presence_penalty=0.4,
            frequency_penalty=0.3,
        )

        reply = completion.choices[0].message.content.strip()

        if not reply:
            return None

        return reply

    except Exception as e:
        print("Groq Error:", e)
        return None


def gemini_chat(user_message, history, user_name=None):

    if not gemini_client:
        return None

    try:

        conversation = chat_system_prompt(user_name)

        conversation += "\n\nConversation History\n\n"

        for msg in history:

            speaker = "User"

            if msg["role"] == "assistant":
                speaker = "MindMate"

            conversation += f"{speaker}: {msg['content']}\n"

        conversation += f"\nUser: {user_message}\nMindMate:"

        response = gemini_client.models.generate_content(
            model=GEMINI_MODEL,
            contents=conversation,
            config={
                "temperature":0.5,
                "top_p":0.9,
                "max_output_tokens":160
            }
        )

        if not response.text:
            return None

        return response.text.strip()

    except Exception as e:
        print("Gemini Error:",e)
        return None
    
import requests   
def ollama_chat(user_message, history=None, user_name=None):

    history = history or []

    payload = {

        "model": OLLAMA_MODEL,

        "messages":[

            {
                "role":"system",
                "content":chat_system_prompt(user_name)
            }

        ] + history +

        [

            {
                "role":"user",
                "content":user_message
            }

        ],

        "stream":False,

        "options":{

            "temperature":0.5,

            "top_p":0.9,

            "num_predict":160

        }

    }

    data = json.dumps(payload).encode()

    req = urllib.request.Request(

        f"{OLLAMA_BASE_URL}/api/chat",

        data=data,

        headers={

            "Content-Type":"application/json"

        },

        method="POST"

    )

    try:

        with urllib.request.urlopen(req,timeout=60) as response:

            body=json.loads(response.read().decode())

        reply=body["message"]["content"].strip()

        return reply if reply else None

    except Exception as e:

        print("Ollama Error:",e)

        return None


def pubmed_search(query, limit=2):
    """
    Search PubMed for research summaries.
    NCBI e-utils: https://www.ncbi.nlm.nih.gov/books/NBK25501/
    """
    base_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
    params = f"?db=pubmed&term={urllib.parse.quote(query)}&retmode=json&retmax={limit}"
    
    try:
        with urllib.request.urlopen(base_url + params, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        
        ids = data.get("esearchresult", {}).get("idlist", [])
        if not ids: return None
        
        # Now fetch summaries for these IDs
        sum_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
        sum_params = f"?db=pubmed&id={','.join(ids)}&retmode=json"
        
        with urllib.request.urlopen(sum_url + sum_params, timeout=10) as resp:
            sum_data = json.loads(resp.read().decode("utf-8"))
        
        results = []
        for pid in ids:
            entry = sum_data.get("result", {}).get(pid, {})
            title = entry.get("title", "No Title")
            source = entry.get("source", "No Source")
            results.append(f"Title: {title}\nPub: {source}\nURL: https://pubmed.ncbi.nlm.nih.gov/{pid}/")
            
        return "\n---\n".join(results)
    except:
        return None


def advanced_chat(user_message, user_id, user_name=None):
    history = get_chat_history(user_id, limit=12) if user_id else []
    lowered = user_message.lower().strip()

    # Crisis Detection
    crisis_terms = [
        "suicide","kill myself","end my life","self harm","self-harm",
        "want to die","better off dead","no reason to live",
        "can't go on","i want to disappear","i don't want to live"
    ]

    if any(t in lowered for t in crisis_terms):
        return crisis_reply()

    # Latest Assessment Context
    assessment_context = ""

    if user_id:
        conn = get_db()
        row = conn.execute(
            """
            SELECT primary_result,recommendation
            FROM assessments
            WHERE user_id=?
            ORDER BY id DESC
            LIMIT 1
            """,
            (user_id,)
        ).fetchone()
        conn.close()
        if row:
            assessment_context = f"""

Latest wellness assessment
Primary concern:
{row['primary_result']}
Recommendation:
{row['recommendation']}
Use this only if it naturally helps.
Do NOT mention the assessment unless relevant.
"""
    # Joke
    if any(k in lowered for k in [
        "joke",
        "funny",
        "make me laugh",
        "cheer me up"
    ]):
        joke = get_random_joke()
        user_message += f"""
The user asked for something funny.
Use this joke naturally.
{joke}
Do not suddenly become motivational afterwards.
"""
    # Scientific Search
    science_keywords = [
        "research",
        "study",
        "science",
        "pubmed",
        "clinical",
        "therapy",
        "cbt",
        "article",
        "paper"
    ]
    if any(k in lowered for k in science_keywords):
        query = user_message[:60]
        pubmed = pubmed_search(query)
        try:
            wiki = wikipedia.summary(query, sentences=2)
        except:
            wiki = None
        if pubmed or wiki:
            context = "\nReliable information\n\n"
            if pubmed:
                context += f"\nPubMed\n{pubmed}\n"
            if wiki:
                context += f"\nWikipedia\n{wiki}\n"
            user_message += f"""
Use the following factual information ONLY if useful.
{context}
Do not copy it.
Explain it naturally.
"""
    # Conversation Memory
    memory = ""
    if history:
        last_messages = history[-8:]
        memory = "Conversation so far:\n"
        for item in last_messages:
            role = "User"
            if item["role"] == "assistant":
                role = "MindMate"
            memory += f"{role}: {item['content']}\n"

    final_message = f"""
Current User Message
{user_message}
{assessment_context}
{memory}
IMPORTANT
Continue this conversation.
Do NOT restart it.
React mainly to the user's LATEST message.
If they are answering your previous question, continue naturally.
Do NOT repeat advice.
Do NOT repeat breathing exercises.
Do NOT repeat the same comforting sentence.
If the user has already made progress, acknowledge it.
If the user is joking, respond naturally.
If they are frustrated, focus on understanding before advising.
Never sound scripted.
"""
    # AI Chain
    reply = groq_chat(
        final_message,
        history,
        user_name
    )
    if not reply:
        reply = gemini_chat(
            final_message,
            history,
            user_name
        )
    if not reply:
        reply = ollama_chat(
            final_message,
            history,
            user_name
        )
    if not reply:
        reply = chat_fallback_reply(
            user_message,
            lowered
        )
    return trim_chat_reply(reply).strip()

def require_login():
    return "user_id" in session


init_db()


@app.context_processor
def inject_globals():
    return {
        "helplines": get_helplines(),
        "logged_in": require_login(),
        "user_name": session.get("user_name"),
    }


@app.route("/")
def home():
    if require_login():
        return render_template("index.html")
    return redirect(url_for("login"))


@app.route("/login", methods=["GET"])
def login():
    if require_login():
        return redirect(url_for("home"))
    return render_template("login.html")


@app.route("/signup", methods=["GET"])
def signup_page():
    if require_login():
        return redirect(url_for("home"))
    return render_template("signup.html")


@app.route("/forgot-password", methods=["GET"])
def forgot_password_page():
    if require_login():
        return redirect(url_for("home"))
    return render_template("forgot_password.html")


@app.route("/reset-password", methods=["GET"])
def reset_password_page():
    if require_login():
        return redirect(url_for("home"))
    return render_template("reset_password.html", token=request.args.get("token", ""))


@app.route("/api/login", methods=["POST"])
def api_login():
    payload = request.get_json(force=True)
    email = (payload.get("email") or "").strip().lower()
    password = payload.get("password") or ""
    if not email or not password:
        return jsonify({"ok": False, "error": "Email and password are required."}), 400

    conn = get_db()
    row = conn.execute(
        "SELECT id, name, password_hash FROM users WHERE email = ?",
        (email,),
    ).fetchone()
    conn.close()

    if not row or not row["password_hash"] or not check_password_hash(row["password_hash"], password):
        return jsonify({"ok": False, "error": "Invalid email or password."}), 401

    session["user_id"] = row["id"]
    session["user_name"] = row["name"]
    return jsonify({"ok": True, "name": row["name"]})


@app.route("/api/forgot-password", methods=["POST"])
def api_forgot_password():
    payload = request.get_json(force=True)
    email = (payload.get("email") or "").strip().lower()
    if not email:
        return jsonify({"ok": False, "error": "Email is required."}), 400

    conn = get_db()
    row = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
    if row:
        token = secrets.token_urlsafe(24)
        expires_at = (datetime.now() + timedelta(minutes=30)).isoformat(timespec="seconds")
        conn.execute(
            "UPDATE users SET reset_token = ?, reset_expires_at = ? WHERE id = ?",
            (token, expires_at, row["id"]),
        )
        conn.commit()
        conn.close()
        return jsonify({
            "ok": True,
            "message": "If that email exists, a reset code has been created. Use it on the next page.",
            "reset_token": token,
        })

    conn.close()
    return jsonify({
        "ok": True,
        "message": "If that email exists, a reset code has been created. Use it on the next page."
    })


@app.route("/api/reset-password", methods=["POST"])
def api_reset_password():
    payload = request.get_json(force=True)
    email = (payload.get("email") or "").strip().lower()
    token = (payload.get("token") or "").strip()
    password = payload.get("password") or ""
    confirm_password = payload.get("confirm_password") or ""

    if not email or not token or not password or not confirm_password:
        return jsonify({"ok": False, "error": "Email, reset code, and a new password are required."}), 400
    if len(password) < 6:
        return jsonify({"ok": False, "error": "New password must be at least 6 characters."}), 400
    if password != confirm_password:
        return jsonify({"ok": False, "error": "Passwords do not match."}), 400

    conn = get_db()
    row = conn.execute(
        "SELECT id, reset_token, reset_expires_at FROM users WHERE email = ?",
        (email,),
    ).fetchone()
    if not row:
        conn.close()
        return jsonify({"ok": False, "error": "No matching account found."}), 404

    try:
        expires_at = datetime.fromisoformat(row["reset_expires_at"]) if row["reset_expires_at"] else None
    except ValueError:
        expires_at = None

    if not row["reset_token"] or row["reset_token"] != token or not expires_at or expires_at < datetime.now():
        conn.close()
        return jsonify({"ok": False, "error": "That reset code is invalid or expired."}), 400

    conn.execute(
        "UPDATE users SET password_hash = ?, reset_token = NULL, reset_expires_at = NULL WHERE id = ?",
        (generate_password_hash(password), row["id"]),
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "message": "Your password has been reset successfully."})


@app.route("/api/signup", methods=["POST"])
def api_signup():
    payload = request.get_json(force=True)
    name = (payload.get("name") or "").strip()
    email = (payload.get("email") or "").strip().lower()
    password = payload.get("password") or ""
    age = payload.get("age")
    if not name or not email or len(password) < 6:
        return jsonify({"ok": False, "error": "Name, valid email, and password (6+ chars) required."}), 400

    conn = get_db()
    try:
        conn.execute(
            """
            INSERT INTO users(name, age, email, password_hash, created_at, total_time_seconds)
            VALUES (?, ?, ?, ?, ?, 0)
            """,
            (
                name,
                age,
                email,
                generate_password_hash(password),
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        conn.commit()
        uid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({"ok": False, "error": "That email is already registered."}), 400
    conn.close()

    session["user_id"] = uid
    session["user_name"] = name
    return jsonify({"ok": True, "user_id": uid, "name": name})


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/api/heartbeat", methods=["POST"])
def heartbeat():
    if not require_login():
        return jsonify({"ok": False}), 401
    payload = request.get_json(force=True)
    seconds = int(payload.get("seconds", 0))
    if seconds <= 0 or seconds > 3600:
        return jsonify({"ok": True})

    uid = session["user_id"]
    day = date.today().isoformat()
    conn = get_db()
    conn.execute(
        "UPDATE users SET total_time_seconds = total_time_seconds + ? WHERE id = ?",
        (seconds, uid),
    )
    row = conn.execute(
        "SELECT seconds FROM usage_daily WHERE user_id = ? AND day = ?",
        (uid, day),
    ).fetchone()
    if row:
        conn.execute(
            "UPDATE usage_daily SET seconds = seconds + ? WHERE user_id = ? AND day = ?",
            (seconds, uid, day),
        )
    else:
        conn.execute(
            "INSERT INTO usage_daily(user_id, day, seconds) VALUES (?, ?, ?)",
            (uid, day, seconds),
        )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/register", methods=["POST"])
def register_legacy():
    """Deprecated: redirect to signup. Kept for old clients."""
    return jsonify({"ok": False, "error": "Please use Sign up with email and password."}), 400


@app.route("/emotion-check")
def emotion_check():
    if not require_login():
        return redirect(url_for("login", next="/emotion-check"))
    return render_template("emotion_check.html")


@app.route("/api/save-emotion", methods=["POST"])
def save_emotion():
    if not require_login():
        return jsonify({"ok": False}), 401
    payload = request.get_json(force=True)
    emotion = payload.get("emotion", "neutral")
    confidence = round(float(payload.get("confidence", 0)), 2)
    session["emotion"] = emotion
    session["emotion_confidence"] = confidence
    return jsonify({"ok": True})


@app.route("/assessment")
def assessment():
    if not require_login():
        return redirect(url_for("login", next="/assessment"))
    return render_template("assessment.html", questions=get_questions())


@app.route("/api/assessment", methods=["POST"])
def save_assessment():
    if not require_login():
        return jsonify({"ok": False, "error": "Please sign in."}), 401

    payload = request.get_json(force=True)
    answers = payload.get("answers", {})
    scores = {"stress": 0, "anxiety": 0, "depression": 0}
    questions = get_questions()
    for q in questions:
        val = int(answers.get(q["id"], 0))
        scores[q["type"]] += val

    emotion = session.get("emotion", "neutral")
    primary = classify_assessment(scores, emotion)
    recommendation = build_recommendation(primary, scores)

    conn = get_db()
    cursor = conn.execute(
        """
        INSERT INTO assessments(user_id, emotion, stress_score, anxiety_score, depression_score,
                                primary_result, recommendation, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            session["user_id"],
            emotion,
            scores["stress"],
            scores["anxiety"],
            scores["depression"],
            primary,
            recommendation,
            datetime.now().isoformat(timespec="seconds"),
        ),
    )
    assessment_id = cursor.lastrowid
    conn.commit()
    conn.close()

    return jsonify(
        {
            "ok": True,
            "assessment_id": assessment_id,
            "scores": scores,
            "primary_result": primary,
            "recommendation": recommendation,
            "emotion": emotion,
        }
    )


@app.route("/result/<int:assessment_id>")
def result(assessment_id):
    if not require_login():
        return redirect(url_for("login"))
    conn = get_db()
    row = conn.execute(
        """
        SELECT a.*, u.name FROM assessments a
        JOIN users u ON a.user_id = u.id
        WHERE a.id = ? AND a.user_id = ?
        """,
        (assessment_id, session["user_id"]),
    ).fetchone()
    conn.close()
    if not row:
        return "Result not found", 404
    return render_template("result.html", row=row)


@app.route("/report/<int:assessment_id>")
def report(assessment_id):
    if not require_login():
        return redirect(url_for("login"))
    conn = get_db()
    row = conn.execute(
        """
        SELECT a.*, u.name FROM assessments a
        JOIN users u ON a.user_id = u.id
        WHERE a.id = ? AND a.user_id = ?
        """,
        (assessment_id, session["user_id"]),
    ).fetchone()
    conn.close()
    if not row:
        return "Report not found", 404

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    styles = getSampleStyleSheet()
    helplines = get_helplines()
    helpline_text = "; ".join([f"{h['name']}: {h['number']}" for h in helplines[:4]])
    story = [
        Paragraph("Mental Health Buddy - Wellness Snapshot", styles["Title"]),
        Spacer(1, 16),
        Paragraph(f"Name: {row['name']}", styles["BodyText"]),
        Paragraph(f"Date: {row['created_at']}", styles["BodyText"]),
        Paragraph(f"Detected facial emotion: {row['emotion']}", styles["BodyText"]),
        Spacer(1, 12),
        Paragraph(f"Primary indicator: {row['primary_result'].title()}", styles["Heading3"]),
        Paragraph(f"Stress score: {row['stress_score']}", styles["BodyText"]),
        Paragraph(f"Anxiety score: {row['anxiety_score']}", styles["BodyText"]),
        Paragraph(f"Depression score: {row['depression_score']}", styles["BodyText"]),
        Spacer(1, 12),
        Paragraph("Recommended next steps", styles["Heading3"]),
        Paragraph(row["recommendation"], styles["BodyText"]),
        Paragraph("Breathing exercise: Try 4-4-6 breathing for 3 minutes.", styles["BodyText"]),
        Paragraph("Music therapy: 10-15 minutes of calm instrumental audio.", styles["BodyText"]),
        Paragraph("India helplines (verify): " + helpline_text, styles["BodyText"]),
        Paragraph("If distress increases, contact emergency services or a trusted person immediately.", styles["BodyText"]),
    ]
    doc.build(story)
    buffer.seek(0)
    return send_file(
        buffer,
        as_attachment=True,
        download_name=f"mental-health-report-{assessment_id}.pdf",
        mimetype="application/pdf",
    )


@app.route("/tools")
def tools():
    if not require_login():
        return redirect(url_for("login"))
    return render_template("tools.html")


@app.route("/chatbot")
def chatbot():
    if not require_login():
        return redirect(url_for("login"))
    return render_template("chatbot.html")


@app.route("/breathing")
def breathing():
    if not require_login():
        return redirect(url_for("login"))
    return render_template("breathing.html", breathing_modes=BREATHING_MODES)


@app.route("/music")
def music():
    if not require_login():
        return redirect(url_for("login"))
    return render_template("music.html", music_tracks=resolve_music_tracks())


@app.route("/jokes")
def good_jokes():
    if not require_login():
        return redirect(url_for("login"))
    all_jokes = get_all_jokes()
    return render_template(
        "jokes.html",
        jokes=all_jokes,
        starter_joke=get_random_joke(),
    )


@app.route("/dashboard")
def dashboard():
    if not require_login():
        return redirect(url_for("login"))
    return render_template("dashboard.html")


@app.route("/help")
def help_page():
    return render_template("help.html")


def build_recent_usage_series(usage_rows, days=7):
    """Return a consistent recent-days series with zero-filled days for easier chart reading."""
    usage_map = {row["day"]: int(row["seconds"] or 0) for row in usage_rows}
    today = date.today()
    labels = []
    values = []
    for offset in range(days - 1, -1, -1):
        day = (today - timedelta(days=offset)).isoformat()
        if offset == 0:
            label = "Today"
        elif offset == 1:
            label = "Yesterday"
        else:
            label = datetime.strptime(day, "%Y-%m-%d").strftime("%a")
        labels.append(label)
        values.append(round((usage_map.get(day, 0) / 60.0), 1))
    return labels, values


@app.route("/api/dashboard-data")
def dashboard_data():
    if not require_login():
        return jsonify({"ok": False}), 401

    uid = session["user_id"]
    range_name = request.args.get("range", "weekly").strip().lower()
    if range_name not in {"weekly", "monthly", "yearly"}:
        range_name = "weekly"

    conn = get_db()
    user_row = conn.execute(
        "SELECT total_time_seconds, name FROM users WHERE id = ?",
        (uid,),
    ).fetchone()
    rows = conn.execute(
        """
        SELECT created_at, stress_score, anxiety_score, depression_score, primary_result
        FROM assessments
        WHERE user_id = ?
        ORDER BY id ASC
        """,
        (uid,),
    ).fetchall()
    assessment_count = len(rows)
    usage_rows = conn.execute(
        """
        SELECT day, seconds FROM usage_daily
        WHERE user_id = ?
        ORDER BY day ASC
        LIMIT 30
        """,
        (uid,),
    ).fetchall()
    tool_rows = conn.execute(
        """
        SELECT tool_name, count, last_used_at
        FROM tool_usage
        WHERE user_id = ?
        ORDER BY count DESC, last_used_at DESC
        """,
        (uid,),
    ).fetchall()
    conn.close()

    labels = []
    stress = []
    anxiety = []
    depression = []
    grouped_counts = {"stress": 0, "anxiety": 0, "depression": 0, "neutral": 0}

    for r in rows:
        created_at = r["created_at"]
        dt = datetime.fromisoformat(created_at)
        if range_name == "weekly":
            bucket = dt.strftime("%Y-%m-%d")
        elif range_name == "monthly":
            bucket = dt.strftime("%Y-%m")
        else:
            bucket = dt.strftime("%Y")

        index = labels.index(bucket) if bucket in labels else None
        if index is None:
            labels.append(bucket)
            stress.append(r["stress_score"])
            anxiety.append(r["anxiety_score"])
            depression.append(r["depression_score"])
        else:
            stress[index] = int((stress[index] + r["stress_score"]) / 2)
            anxiety[index] = int((anxiety[index] + r["anxiety_score"]) / 2)
            depression[index] = int((depression[index] + r["depression_score"]) / 2)

    for r in rows:
        grouped_counts[r["primary_result"]] += 1

    time_labels, time_minutes = build_recent_usage_series(usage_rows, days=7)

    if tool_rows:
        tool_labels = [row["tool_name"] for row in tool_rows]
        tool_values = [int(row["count"] or 0) for row in tool_rows]
        tool_summary = [
            {
                "name": row["tool_name"],
                "count": int(row["count"] or 0),
                "last_used_at": row["last_used_at"],
            }
            for row in tool_rows
        ]
    else:
        tool_labels = []
        tool_values = []
        tool_summary = []

    total_sec = user_row["total_time_seconds"] if user_row else 0

    return jsonify(
        {
            "ok": True,
            "user_name": user_row["name"] if user_row else "",
            "total_time_seconds": total_sec,
            "assessment_count": assessment_count,
            "labels": labels,
            "stress": stress,
            "anxiety": anxiety,
            "depression": depression,
            "summary": grouped_counts,
            "time_labels": time_labels,
            "time_minutes": time_minutes,
            "tool_labels": tool_labels,
            "tool_values": tool_values,
            "tool_summary": tool_summary,
            "range": range_name,
        }
    )


@app.route("/api/track-tool", methods=["POST"])
def track_tool_usage():
    if not require_login():
        return jsonify({"ok": False}), 401

    payload = request.get_json(force=True)
    tool_name = (payload.get("tool_name") or "").strip()
    if not tool_name:
        return jsonify({"ok": False, "error": "Missing tool name."}), 400

    uid = session["user_id"]
    now = datetime.now().isoformat(timespec="seconds")
    conn = get_db()
    row = conn.execute(
        "SELECT id, count FROM tool_usage WHERE user_id = ? AND tool_name = ?",
        (uid, tool_name),
    ).fetchone()
    if row:
        conn.execute(
            "UPDATE tool_usage SET count = count + 1, last_used_at = ? WHERE id = ?",
            (now, row["id"]),
        )
    else:
        conn.execute(
            "INSERT INTO tool_usage(user_id, tool_name, count, last_used_at) VALUES (?, ?, 1, ?)",
            (uid, tool_name, now),
        )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/chat", methods=["POST"])
def chat():
    payload = request.get_json(force=True)
    msg = payload.get("message", "").strip()
    lowered = msg.lower()

    risk_terms = [
        "suicide", "kill myself", "end my life", "self harm", "self-harm",
        "want to die", "no reason to live", "hang myself", "cut myself",
    ]
    if any(term in lowered for term in risk_terms):
        reply = crisis_reply()
    elif msg:
        uid = session.get("user_id")
        user_name = session.get("user_name")
        reply = advanced_chat(
                user_message=msg,
                user_id=uid,
                user_name=user_name
        )
    else:
        reply = "I am here with you. What would you like to share?"

    if require_login() and msg:
        conn = get_db()
        conn.execute(
            "INSERT INTO chat_logs(user_id, user_message, bot_reply, created_at) VALUES (?, ?, ?, ?)",
            (session["user_id"], msg, reply, datetime.now().isoformat(timespec="seconds")),
        )
        conn.commit()
        conn.close()

    return jsonify(
        {
            "reply": reply,
            "time_context": get_time_context(),
            "vulnerable_night": is_vulnerable_night_window(),
            "ollama_configured": True,
        }
    )


@app.route("/api/chat-history")
def api_chat_history():
    if not require_login():
        return jsonify({"ok": False}), 401
    
    uid = session["user_id"]
    conn = get_db()
    # Fetch last 50 messages to keep UI clean but persistent
    rows = conn.execute(
        "SELECT user_message, bot_reply, created_at FROM chat_logs WHERE user_id = ? ORDER BY id ASC LIMIT 50",
        (uid,),
    ).fetchall()
    conn.close()
    
    history = []
    for r in rows:
        history.append({
            "user": r["user_message"],
            "bot": r["bot_reply"],
            "at": r["created_at"]
        })
    
    return jsonify({"ok": True, "history": history})


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=os.getenv("FLASK_DEBUG") == "1")
