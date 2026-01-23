import os
import json
import uuid
import threading
import requests
import redis
import time
import logging
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, constr
from openai import OpenAI

# =====================
# LOGGING
# =====================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("konstrategy")

# =====================
# ENV
# =====================
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
APIFY_TOKEN = os.getenv("APIFY_TOKEN")
APIFY_PROFILE_TASK_ID = os.getenv("APIFY_PROFILE_TASK_ID")
APIFY_POSTS_TASK_ID = os.getenv("APIFY_POSTS_TASK_ID")
REDIS_URL = os.getenv("REDIS_URL")

if not all([OPENAI_API_KEY, APIFY_TOKEN, APIFY_PROFILE_TASK_ID, APIFY_POSTS_TASK_ID, REDIS_URL]):
    raise RuntimeError("Faltan variables de entorno requeridas")

client = OpenAI(api_key=OPENAI_API_KEY)
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

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
# RATE LIMIT
# =====================
def rate_limit(request: Request):
    ip = request.client.host
    key = f"rate:{ip}"

    count = redis_client.get(key)
    if count and int(count) >= 5:
        raise HTTPException(status_code=429, detail="Límite alcanzado (5 análisis por hora)")

    pipe = redis_client.pipeline()
    pipe.incr(key, 1)
    pipe.expire(key, 3600)
    pipe.execute()

# =====================
# APIFY HELPERS
# =====================
def start_apify_task(task_id: str, payload: dict) -> str:
    url = f"https://api.apify.com/v2/actor-tasks/{task_id}/runs"
    res = requests.post(
        url,
        params={"token": APIFY_TOKEN},
        json=payload,
        timeout=30
    )
    if res.status_code not in (200, 201):
        raise RuntimeError(f"Apify Start Error: {res.text}")
    return res.json()["data"]["id"]

def wait_for_apify_run(run_id: str, timeout: int = 300) -> str:
    start = time.time()
    while time.time() - start < timeout:
        res = requests.get(
            f"https://api.apify.com/v2/actor-runs/{run_id}",
            params={"token": APIFY_TOKEN},
            timeout=20
        )
        status = res.json()["data"]["status"]
        logger.info(f"Apify Run {run_id} status: {status}")

        if status == "SUCCEEDED":
            return res.json()["data"]["defaultDatasetId"]
        if status in ("FAILED", "ABORTED", "TIMED-OUT"):
            raise RuntimeError(f"Apify run failed: {status}")

        time.sleep(5)

    raise RuntimeError("Apify timeout")

def get_apify_dataset(dataset_id: str) -> list:
    res = requests.get(
        f"https://api.apify.com/v2/datasets/{dataset_id}/items",
        params={"token": APIFY_TOKEN},
        timeout=30
    )
    return res.json()

# =====================
# GPT ANALYSIS (SDK NUEVO)
# =====================
def analyze_with_gpt(images: list, captions: list) -> dict:
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

Contexto de captions:
{json.dumps(captions[:10], ensure_ascii=False)}
"""

    content = [{"type": "input_text", "text": prompt}]

    for img_url in images[:6]:
        content.append({
            "type": "input_image",
            "image_url": img_url
        })

    response = client.responses.create(
        model="gpt-4o-mini",
        input=[{
            "role": "user",
            "content": content
        }],
        max_output_tokens=500
    )

    return json.loads(response.output_text)

# =====================
# WORKER
# =====================
def run_analysis(job_id: str, username: str):
    try:
        logger.info(f"Iniciando análisis para {username}")

        raw = username.replace("@", "").strip()
        instagram_url = f"https://www.instagram.com/{raw}/"

        # PROFILE
        profile_run = start_apify_task(
            APIFY_PROFILE_TASK_ID,
            {"instagramUrls": [instagram_url]}
        )
        profile_dataset = wait_for_apify_run(profile_run)
        profile_items = get_apify_dataset(profile_dataset)

        if not profile_items:
            raise RuntimeError("Perfil no encontrado")

        profile = profile_items[0]

        # POSTS
        posts_run = start_apify_task(
            APIFY_POSTS_TASK_ID,
            {
                "instagramUrls": [instagram_url],
                "resultsLimit": 15
            }
        )
        posts_dataset = wait_for_apify_run(posts_run)
        posts_data = get_apify_dataset(posts_dataset)

        images, captions = [], []

        for p in posts_data:
            img = p.get("displayUrl") or p.get("thumbnailUrl")
            if img:
                images.append(img)
            text = p.get("caption") or p.get("text")
            if text:
                captions.append(text)

        if not images:
            raise RuntimeError("No se encontraron imágenes")

        # GPT
        analysis = analyze_with_gpt(images, captions)

        total_score = round(sum(analysis["scores"].values()) / 5 * 10, 1)

        result = {
            "status": "done",
            "data": {
                "profile": {
                    "username": raw,
                    "icon": profile.get("profilePicUrl"),
                    "followers": profile.get("followersCount"),
                    "posts": profile.get("postsCount"),
                },
                "total_score": total_score,
                "scores": analysis["scores"],
                "dominant_content_type": analysis["dominant_content_type"],
                "interpretation": analysis["interpretation"]
            }
        }

        redis_client.setex(f"job:{job_id}", 3600, json.dumps(result))
        logger.info(f"Análisis completado para {username}")

    except Exception as e:
        logger.exception("Error en análisis")
        redis_client.setex(
            f"job:{job_id}",
            3600,
            json.dumps({"status": "error", "error": str(e)})
        )

# =====================
# ROUTES
# =====================
@app.post("/analysis/start")
def start_analysis(data: VisualAnalysisRequest, request: Request):
    rate_limit(request)

    job_id = str(uuid.uuid4())
    redis_client.setex(f"job:{job_id}", 3600, json.dumps({"status": "processing"}))

    thread = threading.Thread(
        target=run_analysis,
        args=(job_id, data.username),
        daemon=True
    )
    thread.start()

    return {"job_id": job_id}

@app.get("/analysis/status/{job_id}")
def analysis_status(job_id: str):
    job = redis_client.get(f"job:{job_id}")
    if not job:
        raise HTTPException(status_code=404, detail="Job expirado o no encontrado")
    return json.loads(job)
