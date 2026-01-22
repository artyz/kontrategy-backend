import os
import json
import time
import requests
from typing import List
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import OpenAI

# =====================
# ENV
# =====================
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
APIFY_TOKEN = os.getenv("APIFY_TOKEN")

if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY missing")

if not APIFY_TOKEN:
    raise RuntimeError("APIFY_TOKEN missing")

client = OpenAI(api_key=OPENAI_API_KEY)

# =====================
# APIFY CONFIG
# =====================
APIFY_TASK_ID = "j9cZg41h6HafO2n1R"
APIFY_BASE_URL = "https://api.apify.com/v2"

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
    username: str

# =====================
# APIFY HELPERS
# =====================
def run_apify_task(instagram_url: str) -> str:
    url = f"{APIFY_BASE_URL}/actor-tasks/{APIFY_TASK_ID}/run-sync-get-dataset-items"
    params = {
        "token": APIFY_TOKEN,
        "clean": "true"
    }

    payload = {
        "directUrls": [instagram_url],
        "resultsLimit": 30
    }

    res = requests.post(url, params=params, json=payload, timeout=120)
    res.raise_for_status()
    return res.json()

# =====================
# GPT ANALYSIS
# =====================
def analyze_with_gpt(images: List[str], captions: List[str]) -> dict:
    prompt = f"""
Analiza el LOOK & FEEL visual de este perfil de Instagram.

Evalúa del 1 al 5:
- paleta_colores
- consistencia_grafica
- ruido_visual
- calidad_visual
- presencia_humana

Devuelve SOLO JSON válido con este formato:

{{
  "scores": {{
    "paleta_colores": 1,
    "ruido_visual": 1,
    "consistencia_grafica": 1,
    "calidad_visual": 1,
    "presencia_humana": 1
  }},
  "interpretation": "Análisis visual profesional"
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
                        for img in images[:8]
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
    username = data.username.replace("@", "").strip().lower()
    instagram_url = f"https://www.instagram.com/{username}/"

    # =====================
    # APIFY SCRAPE
    # =====================
    dataset = run_apify_task(instagram_url)

    if not dataset or len(dataset) == 0:
        return {"status": "error", "message": "No data from Apify"}

    profile = dataset[0]

    # =====================
    # PROFILE DATA
    # =====================
    profile_data = {
        "username": username,
        "full_name": profile.get("fullName"),
        "biography": profile.get("biography"),
        "category": profile.get("businessCategoryName"),
        "profile_pic": profile.get("profilePicUrl"),
        "followers": profile.get("followersCount"),
        "following": profile.get("followsCount"),
        "posts": profile.get("postsCount"),
    }

    # =====================
    # POSTS / IMAGES
    # =====================
    images = []
    captions = []

    for post in profile.get("latestPosts", []):
        if post.get("displayUrl"):
            images.append(post["displayUrl"])
        if post.get("caption"):
            captions.append(post["caption"])

    if len(images) < 3:
        return {
            "status": "error",
            "message": "Not enough images for visual analysis",
            **profile_data
        }

    # =====================
    # GPT VISION
    # =====================
    analysis = analyze_with_gpt(images, captions)
    scores = analysis["scores"]
    total_score = sum(scores.values())

    return {
        "status": "ok",
        **profile_data,
        "scores": scores,
        "total_score": total_score,
        "score_over_10": round((total_score / 25) * 10, 1),
        "interpretation": analysis["interpretation"]
    }
