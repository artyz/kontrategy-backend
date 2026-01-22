import os
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
APIFY_PROFILE_TASK_ID = os.getenv("APIFY_PROFILE_TASK_ID")
APIFY_POSTS_TASK_ID = os.getenv("APIFY_POSTS_TASK_ID")

if not all([
    OPENAI_API_KEY,
    APIFY_TOKEN,
    APIFY_PROFILE_TASK_ID,
    APIFY_POSTS_TASK_ID
]):
    raise RuntimeError("Missing environment variables")

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
# APIFY HELPERS
# =====================
def run_task(task_id: str, payload: dict) -> list[dict]:
    url = (
        f"https://api.apify.com/v2/actor-tasks/"
        f"{task_id}/run-sync-get-dataset-items"
        f"?token={APIFY_TOKEN}"
    )

    res = requests.post(url, json=payload, timeout=180)

    if res.status_code != 200:
        raise RuntimeError(f"Apify task failed: {res.text}")

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

    response = client.chat.completions.create(
        model="gpt-4o",
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "user",
                "content": (
                    [{"type": "text", "text": prompt}] +
                    [{"type": "image_url", "image_url": {"url": img}} for img in images[:6]]
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
        username = raw.replace("@", "")
        instagram_url = f"https://www.instagram.com/{username}/"

    # =====================
    # PROFILE TASK
    # =====================
    profile_items = run_task(
        APIFY_PROFILE_TASK_ID,
        {"instagramUrls": [instagram_url]}
    )

    if not profile_items:
        raise HTTPException(404, "Profile not found")

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

    # =====================
    # POSTS TASK
    # =====================
    posts_items = run_task(
        APIFY_POSTS_TASK_ID,
        {
            "instagramUrls": [instagram_url],
            "resultsLimit": 20
        }
    )

    images = []
    captions = []

    for item in posts_items:
        if item.get("displayUrl"):
            images.append(item["displayUrl"])
        if item.get("caption"):
            captions.append(item["caption"])

    if len(images) < 3:
        raise HTTPException(400, "Not enough images")

    # =====================
    # GPT
    # =====================
    analysis = analyze_with_gpt(images, captions)
    total_score = sum(analysis["scores"].values())

    return {
        "status": "ok",
        "profile": profile_info,
        "scores": analysis["scores"],
        "total_score": round(total_score / 5 * 10, 1),
        "dominant_content_type": analysis["dominant_content_type"],
        "interpretation": analysis["interpretation"]
    }
