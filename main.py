import os
import json
import uuid
import threading
import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, constr
from openai import OpenAI

# =====================
# ENV
# =====================
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
APIFY_TOKEN = os.getenv("APIFY_TOKEN")
APIFY_PROFILE_TASK_ID = os.getenv("APIFY_PROFILE_TASK_ID")
APIFY_POSTS_TASK_ID = os.getenv("APIFY_POSTS_TASK_ID")

client = OpenAI(api_key=OPENAI_API_KEY)

# =====================
# IN-MEMORY STORE (MVP)
# =====================
JOBS = {}

# =====================
# APP
# =====================
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =====================
# MODELS
# =====================
class VisualAnalysisRequest(BaseModel):
    username: constr(min_length=1, max_length=200)

# =====================
# APIFY
# =====================
def run_task(task_id: str, payload: dict) -> list:
    url = (
        f"https://api.apify.com/v2/actor-tasks/"
        f"{task_id}/run-sync-get-dataset-items"
        f"?token={APIFY_TOKEN}"
    )

    res = requests.post(url, json=payload, timeout=180)
    if res.status_code != 200:
        raise RuntimeError(res.text)

    return res.json()

# =====================
# GPT
# =====================
def analyze_with_gpt(images, captions):
    prompt = f"""
Analiza el LOOK & FEEL de un perfil de Instagram.

Devuelve SOLO JSON válido:

{{
  "scores": {{
    "paleta_colores": 1,
    "ruido_visual": 1,
    "consistencia_grafica": 1,
    "calidad_visual": 1,
    "presencia_humana": 1
  }},
  "dominant_content_type": "educativo | entretenimiento | promocional | mixto",
  "interpretation": "Análisis visual profesional breve"
}}

Contexto textual:
{json.dumps(captions, ensure_ascii=False)}
"""

    response = client.responses.create(
        model="gpt-4.1-mini",
        input=[{
            "role": "user",
            "content": (
                [{"type": "input_text", "text": prompt}] +
                [{"type": "input_image", "image_url": img} for img in images[:6]]
            )
        }]
    )

    return json.loads(response.output_text)

# =====================
# WORKER
# =====================
def run_analysis(job_id: str, username: str):
    try:
        raw = username.strip()

        if raw.startswith("http"):
            instagram_url = raw.rstrip("/")
            username = raw.rstrip("/").split("/")[-1]
        else:
            username = raw.replace("@", "")
            instagram_url = f"https://www.instagram.com/{username}/"

        # PROFILE
        profile_items = run_task(
            APIFY_PROFILE_TASK_ID,
            {"instagramUrls": [instagram_url]}
        )

        if not profile_items:
            raise Exception("Profile not found")

        profile = profile_items[0]

        profile_info = {
            "username": username,
            "icon": profile.get("profilePicUrl"),
            "category": profile.get("businessCategoryName"),
            "description": profile.get("biography"),
            "followers": profile.get("followersCount"),
            "following": profile.get("followsCount"),
            "posts": profile.get("postsCount"),
        }

        # POSTS
        posts_items = run_task(
            APIFY_POSTS_TASK_ID,
            {
                "instagramUrls": [instagram_url],
                "resultsLimit": 20
            }
        )

        images, captions = [], []

        for item in posts_items:
            img = item.get("displayUrl") or item.get("thumbnailUrl")
            if img:
                images.append(img)

            text = item.get("caption") or item.get("text")
            if text:
                captions.append(text)

        if len(images) < 1:
            raise Exception("No usable images found")

        analysis = analyze_with_gpt(images, captions)
        total_score = round(sum(analysis["scores"].values()) / 5 * 10, 1)

        JOBS[job_id] = {
            "status": "done",
            "data": {
                "profile": profile_info,
                "scores": analysis["scores"],
                "total_score": total_score,
                "dominant_content_type": analysis["dominant_content_type"],
                "interpretation": analysis["interpretation"]
            }
        }

    except Exception as e:
        JOBS[job_id] = {
            "status": "error",
            "error": str(e)
        }

# =====================
# ROUTES
# =====================
@app.get("/")
def root():
    return {"status": "ok"}

@app.post("/analysis/start")
def start_analysis(data: VisualAnalysisRequest):
    job_id = str(uuid.uuid4())
    JOBS[job_id] = {"status": "processing"}

    thread = threading.Thread(
        target=run_analysis,
        args=(job_id, data.username),
        daemon=True
    )
    thread.start()

    return {"job_id": job_id}

@app.get("/analysis/status/{job_id}")
def get_status(job_id: str):
    if job_id not in JOBS:
        raise HTTPException(404, "Job not found")
    return JOBS[job_id]
