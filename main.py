import os
import json
import uuid
import threading
import requests
import redis
import time
from fastapi import FastAPI, HTTPException, Request
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
# RATE LIMIT (5 / HORA)
# =====================
def rate_limit(request: Request):
    ip = request.client.host
    key = f"rate:{ip}"
    count = r.get(key)

    if count and int(count) >= 5:
        raise HTTPException(429, "Límite alcanzado (5 análisis por hora)")

    pipe = r.pipeline()
    pipe.incr(key, 1)
    pipe.expire(key, 3600)
    pipe.execute()

# =====================
# APIFY ASYNC HELPERS
# =====================
def start_task(task_id, payload):
    url = f"https://api.apify.com/v2/actor-tasks/{task_id}/runs?token={APIFY_TOKEN}"
    res = requests.post(url, json=payload, timeout=30)
    if res.status_code not in (200, 201):
        raise Exception(res.text)
    return res.json()["data"]["id"]

def wait_for_run(run_id, timeout=120):
    start = time.time()
    while time.time() - start < timeout:
        res = requests.get(
            f"https://api.apify.com/v2/actor-runs/{run_id}",
            params={"token": APIFY_TOKEN},
            timeout=20
        )
        status = res.json()["data"]["status"]

        if status == "SUCCEEDED":
            return res.json()["data"]["defaultDatasetId"]

        if status in ("FAILED", "ABORTED", "TIMED-OUT"):
            raise Exception(f"Apify run failed: {status}")

        time.sleep(5)

    raise Exception("Apify timeout")

def get_dataset(dataset_id):
    res = requests.get(
        f"https://api.apify.com/v2/datasets/{dataset_id}/items",
        params={"token": APIFY_TOKEN},
        timeout=30
    )
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
        raw = username.replace("@", "").strip()
        instagram_url = f"https://www.instagram.com/{raw}/"

        # PROFILE
        profile_run = start_task(
            APIFY_PROFILE_TASK_ID,
            {"instagramUrls": [instagram_url]}
        )
        profile_dataset = wait_for_run(profile_run)
        profile_items = get_dataset(profile_dataset)

        if not profile_items:
            raise Exception("Profile not found")

        profile = profile_items[0]

        # POSTS
        posts_run = start_task(
            APIFY_POSTS_TASK_ID,
            {"instagramUrls": [instagram_url], "resultsLimit": 20}
        )
        posts_dataset = wait_for_run(posts_run)
        posts = get_dataset(posts_dataset)

        images, captions = [], []
        for p in posts:
            img = p.get("displayUrl") or p.get("thumbnailUrl")
            if img:
                images.append(img)

            text = p.get("caption") or p.get("text")
            if text:
                captions.append(text)

        if not images:
            raise Exception("No usable images")

        analysis = analyze_with_gpt(images, captions)
        score = round(sum(analysis["scores"].values()) / 5 * 10, 1)

        r.setex(
            f"job:{job_id}",
            3600,
            json.dumps({
                "status": "done",
                "data": {
                    "profile": {
                        "username": raw,
                        "icon": profile.get("profilePicUrl"),
                        "followers": profile.get("followersCount"),
                        "posts": profile.get("postsCount"),
                    },
                    "total_score": score,
                    "dominant_content_type": analysis["dominant_content_type"],
                    "interpretation": analysis["interpretation"]
                }
            })
        )

    except Exception as e:
        r.setex(
            f"job:{job_id}",
            3600,
            json.dumps({
                "status": "error",
                "error": str(e)
            })
        )

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
