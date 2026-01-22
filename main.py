import os
import time
import json
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
APIFY_TASK_ID = os.getenv("APIFY_TASK_ID")  # ej: j9cZg41h6HafO2n1R

if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY missing")

if not APIFY_TOKEN or not APIFY_TASK_ID:
    raise RuntimeError("APIFY_TOKEN or APIFY_TASK_ID missing")

client = OpenAI(api_key=OPENAI_API_KEY)

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
def run_apify_task(instagram_url: str) -> list[dict]:
    run_url = (
        f"https://api.apify.com/v2/actor-tasks/"
        f"{APIFY_TASK_ID}/run-sync-get-dataset-items"
    )

    payload = {
        "instagramUrls": [instagram_url],
        "resultsLimit": 12
    }

    res = requests.post(
        f"{run_url}?token={APIFY_TOKEN}",
        json=payload,
        timeout=180
    )

    if res.status_code != 200:
        raise RuntimeError("Apify task failed")

    return res.json()

# =====================
# GPT ANALYSIS
# =====================
def analyze_with_gpt(images: list[str], captions: list[str]) -> dict:
    prompt = f"""
Analiza el LOOK & FEEL de un perfil de Instagram.

Evalúa:
- Paleta de colores
- Consistencia visual
- Ruido visual
- Calidad gráfica
- Presencia humana
- Tipo de contenido dominante

Devuelve SOLO JSON válido con este formato:

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

    response = client.chat.completions.create(
        model="gpt-4o",
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "user",
                "content": (
                    [{"type": "text", "text": prompt}]
                    + [
                        {
                            "type": "image_url",
                            "image_url": {"url": img}
                        }
                        for img in images[:6]
                    ]
                )
            }
        ],
        max_tokens=500
    )

    return json.loads(response.choices[0].message.content)

# =====================
# ROUTES
# =====================
@app.get("/")
def root():
    return {"status": "Kontrategy backend alive"}

@app.post("/analysis/visual")
def visual_analysis(data: VisualAnalysisRequest):
    raw = data.username.strip()

    if raw.startswith("http"):
        username = raw.rstrip("/").split("/")[-1]
        instagram_url = raw
    else:
        username = raw.replace("@", "").lower()
        instagram_url = f"https://www.instagram.com/{username}/"

    # =====================
    # APIFY DATA
    # =====================
    items = run_apify_task(instagram_url)

    if not items:
        raise HTTPException(status_code=404, detail="No data from Apify")

    profile = items[0]

    # =====================
    # PROFILE INFO
    # =====================
    profile_info = {
        "username": username,
        "icon": profile.get("profilePicUrl"),
        "category": profile.get("businessCategoryName"),
        "description": profile.get("biography"),
        "followers": profile.get("followersCount"),
        "following": profile.get("followsCount"),
        "posts": profile.get("postsCount"),
    }

    # =====================
    # IMAGES + CAPTIONS
    # =====================
    images = []
    captions = []

    for item in items:
        img = item.get("displayUrl")
        if img:
            images.append(img)

        caption = item.get("caption")
        if caption:
            captions.append(caption)

    if len(images) < 3:
        raise HTTPException(status_code=400, detail="Not enough images")

    # =====================
    # GPT ANALYSIS
    # =====================
    analysis = analyze_with_gpt(images, captions)

    scores = analysis["scores"]
    total_score = sum(scores.values())

    return {
        "status": "ok",
        "profile": profile_info,
        "scores": scores,
        "total_score": round(total_score / 5 * 10, 1),
        "dominant_content_type": analysis["dominant_content_type"],
        "interpretation": analysis["interpretation"]
    }
