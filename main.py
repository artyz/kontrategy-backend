import os
import json
import uuid
import threading
import requests
import redis
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, constr
from openai import OpenAI
from time import time

# =====================
# ENV
# =====================
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
APIFY_TOKEN = os.getenv("APIFY_TOKEN")
APIFY_PROFILE_TASK_ID = os.getenv("APIFY_PROFILE_TASK_ID")
APIFY_POSTS_TASK_ID = os.getenv("APIFY_POSTS_TASK_ID")
REDIS_URL = os.getenv("REDIS_URL")

client = OpenAI(api_key=OPENAI_API_KEY)
r = redis.from_url(REDIS_URL, decode_responses=True)

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
# RATE LIMIT (5 / hora por IP)
# =====================
def rate_limit(request: Request):
    ip = request.client.host
    key = f"rate:{ip}"
    count = r.get(key)

    if count and int(count) >= 5:
        raise HTTPException(429, "Límite alcanzado (5 análisis / hora)")

    pipe = r.pipeline()
    pipe.incr(key, 1)
    pipe.expire(key, 3600)
    pipe.execute()

# =====================
# APIFY
# =====================
def run_task(task_id, payload):
    url = f"https://api.apify.com/v2/actor-tasks/{task_id}/run-sync-get-dataset-items?token={APIFY_TOKEN}"
    res = requests.post(url, json=payload, timeout=180)
    if res.status_code != 200:
        raise Exception(res.text)
    return res.json()

# =====================
# GPT
# =====================
def analyze_with_gpt(images, captions):
    prompt = f"""
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

Contexto:
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
def run_analysis(job_id, username):
    try:
        raw = username.replace("@", "")
        instagram_url = f"https://www.instagram.com/{raw}/"

        profile = run_task(
            APIFY_PROFILE_TASK_ID,
            {"instagramUrls": [instagram_url]}
        )[0]

        posts = run_task(
            APIFY_POSTS_TASK_ID,
            {"instagramUrls": [instagram_url], "resultsLimit": 20}
        )

        images, captions = [], []
        for p in posts:
            if p.get("displayUrl") or p.get("thumbnailUrl"):
                images.append(p.get("displayUrl") or p.get("thumbnailUrl"))
            if p.get("caption") or p.get("text"):
                captions.append(p.get("caption") or p.get("text"))

        analysis = analyze_with_gpt(images, captions)
        score = round(sum(analysis["scores"].values()) / 5 * 10, 1)

        r.setex(f"job:{job_id}", 3600, json.dumps({
            "status": "done",
            "data": {
                "profile": {
                    "username": raw,
                    "icon": profile.get("profilePicUrl"),
                    "followers": profile.get("followersCount"),
                    "posts": profile.get("postsCount")
                },
                "total_score": score,
                "interpretation": analysis["interpretation"]
            }
        }))

    except Exception as e:
        r.setex(f"job:{job_id}", 3600, json.dumps({
            "status": "error",
            "error": str(e)
        }))

# =====================
# ROUTES
# =====================
@app.post("/analysis/start")
def start(data: VisualAnalysisRequest, request: Request):
    rate_limit(request)

    job_id = str(uuid.uuid4())
    r.setex(f"job:{job_id}", 3600, json.dumps({"status": "processing"}))

    threading.Thread(
        target=run_analysis,
        args=(job_id, data.username),
        daemon=True
    ).start()

    return {"job_id": job_id}

@app.get("/analysis/status/{job_id}")
def status(job_id: str):
    job = r.get(f"job:{job_id}")
    if not job:
        raise HTTPException(404, "Job expirado")
    return json.loads(job)
