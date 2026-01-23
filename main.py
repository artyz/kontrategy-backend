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

# Configuración de Logs para ver qué pasa en segundo plano
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# =====================
# ENV
# =====================
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
APIFY_TOKEN = os.getenv("APIFY_TOKEN")
APIFY_PROFILE_TASK_ID = os.getenv("APIFY_PROFILE_TASK_ID")
APIFY_POSTS_TASK_ID = os.getenv("APIFY_POSTS_TASK_ID")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

client = OpenAI(api_key=OPENAI_API_KEY)
r = redis.from_url(REDIS_URL, decode_responses=True)

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
# HELPERS
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

def start_apify_task(task_id, payload):
    url = f"https://api.apify.com/v2/actor-tasks/{task_id}/runs?token={APIFY_TOKEN}"
    res = requests.post(url, json=payload, timeout=30)
    if res.status_code not in (200, 201):
        raise Exception(f"Apify Start Error: {res.text}")
    return res.json()["data"]["id"]

def wait_for_apify_run(run_id, timeout=300): # Aumentado a 5 min
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
            raise Exception(f"Apify run failed: {status}")
        time.sleep(5)
    raise Exception("Apify timeout")

def get_apify_dataset(dataset_id):
    res = requests.get(
        f"https://api.apify.com/v2/datasets/{dataset_id}/items",
        params={"token": APIFY_TOKEN},
        timeout=30
    )
    return res.json()

# =====================
# GPT ANALYSIS (FIXED)
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

Contexto de captions:
{json.dumps(captions[:10], ensure_ascii=False)}
"""
    # Construcción correcta del mensaje para GPT-4o-mini con imágenes
    content = [{"type": "text", "text": prompt}]
    
    # Solo enviamos las primeras 6 imágenes para evitar timeouts y costos excesivos
    for img_url in images[:6]:
        content.append({
            "type": "image_url",
            "image_url": {"url": img_url}
        })

    response = client.chat.completions.create(
        model="gpt-4o-mini", # El modelo correcto
        messages=[{"role": "user", "content": content}],
        response_format={"type": "json_object"},
        max_tokens=500
    )
    
    return json.loads(response.choices[0].message.content)

# =====================
# WORKER
# =====================
def run_analysis(job_id, username):
    try:
        logger.info(f"Iniciando análisis para: {username}")
        raw = username.replace("@", "").strip()
        instagram_url = f"https://www.instagram.com/{raw}/"

        # 1. PROFILE
        logger.info("Obteniendo perfil...")
        p_run = start_apify_task(APIFY_PROFILE_TASK_ID, {"instagramUrls": [instagram_url]})
        p_dataset = wait_for_apify_run(p_run)
        p_items = get_apify_dataset(p_dataset)
        if not p_items: raise Exception("Perfil no encontrado en Instagram")
        profile = p_items[0]

        # 2. POSTS
        logger.info("Obteniendo posts...")
        posts_run = start_apify_task(APIFY_POSTS_TASK_ID, {"instagramUrls": [instagram_url], "resultsLimit": 15})
        posts_dataset = wait_for_apify_run(posts_run)
        posts_data = get_apify_dataset(posts_dataset)

        images, captions = [], []
        for p in posts_data:
            img = p.get("displayUrl") or p.get("thumbnailUrl")
            if img: images.append(img)
            text = p.get("caption") or p.get("text")
            if text: captions.append(text)

        if not images: raise Exception("No se encontraron imágenes para analizar")

        # 3. GPT
        logger.info("Enviando a GPT-4o-mini...")
        analysis = analyze_with_gpt(images, captions)
        
        # Calcular promedio
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
        r.setex(f"job:{job_id}", 3600, json.dumps(result))
        logger.info(f"Análisis completado para {username}")

    except Exception as e:
        logger.error(f"Error en worker: {str(e)}")
        r.setex(f"job:{job_id}", 3600, json.dumps({"status": "error", "error": str(e)}))

# =====================
# ROUTES
# =====================
@app.post("/analysis/start")
def start(data: VisualAnalysisRequest, request: Request):
    rate_limit(request)
    job_id = str(uuid.uuid4())
    
    r.setex(f"job:{job_id}", 3600, json.dumps({"status": "processing"}))

    thread = threading.Thread(
        target=run_analysis,
        args=(job_id, data.username),
        daemon=True
    )
    thread.start()

    return {"job_id": job_id}

@app.get("/analysis/status/{job_id}")
def status(job_id: str):
    job = r.get(f"job:{job_id}")
    if not job:
        raise HTTPException(404, "Job expirado o no encontrado")
    return json.loads(job)
