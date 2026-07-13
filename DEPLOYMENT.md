# Deploying Mental Health Buddy

This project is ready for Render as a Python web service.

## Render settings

- Root directory: leave blank if this folder is the GitHub repository root. If the parent folder is the repository root, set it to `Mental-Health-Buddy`.
- Build command: `pip install -r requirements.txt`
- Start command: `gunicorn app:app`
- Health check path: `/`

## Environment variables

Set these in the Render dashboard. Do not commit `.env`.

- `FLASK_SECRET_KEY`: generate a long random value
- `DATABASE_PATH`: `/var/data/mental_buddy.db`
- `GROQ_API_KEY`: your Groq API key, if using Groq
- `GEMINI_API_KEY`: your Gemini API key, if using Gemini
- `GROQ_MODEL`: `llama-3.3-70b-versatile`
- `GEMINI_MODEL`: `gemini-2.0-flash`

For SQLite persistence on Render, add a disk:

- Mount path: `/var/data`
- Size: `1 GB`

## Important

Rotate any API keys that were ever stored in `.env` before pushing to GitHub.
