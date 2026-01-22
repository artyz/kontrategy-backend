import os
import json
import requests
from typing import List, Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, constr
from openai import OpenAI

# =====================
# ENV
# =====================
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
APIFY_TOKEN = os.getenv("APIFY_TOKEN")
APIFY_TASK_ID = os.getenv("APIFY_TASK_ID")

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
    mode: str = "detail"  # summary | detail

# =====================
# APIFY
# =====================
def fetch_instagram_assets(username: str, limit: int = 12):
    """
    Obtiene imágenes y captions reales desde Instagram vía Apify
    """
    url = (
        f"https://api.apify.com/v2/actor-tasks/"
        f"{APIFY_TASK_ID}/run-sync-get-dataset-items"
        f"?token={APIFY_TOKEN}"
    )

    payload = {
        "directUrls": [f"https://www.instagram.com/{username}/"],
        "resultsLimit": limit,
        "resultsType": "posts"
    }

    res = requests.post(url, json=payload, timeout=90)
    res.raise_for_status()

    data = res.json()

    images = []
    captions = []

    for item in data:
        if item.get("displayUrl"):
            images.append(item["displayUrl"])
            captions.append(item.get("caption", ""))

    return images, captions

# =====================
# GPT ANALYSIS
# =====================
def analyze_with_gpt(images: List[str], captions: List[str]) -> dict:
    prompt = f"""
Analiza VISUALMENTE este perfil de Instagram basándote SOLO en las imágenes.

Evalúa:
- Paleta de colores
- Consistencia visual
- Ruido visual
- Calidad gráfica
- Presencia humana

Determina además:
- Tipo de contenido dominante (educativo, entretenimiento, promocional, mixto)

Devuelve SOLO JSON válido con este formato EXACTO:

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

Contexto textual (captions):
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
                        for img in images
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
    else:
        username = raw.replace("@", "").replace("/", "").lower()

    # =====================
    # SUMMARY MODE
    # =====================
    if data.mode == "summary":
        return {
            "status": "ok",
            "username": username,
            "scores": {
                "paleta_colores": 4,
                "ruido_visual": 3,
                "consistencia_grafica": 4,
                "calidad_visual": 4,
                "presencia_humana": 3
            },
            "total_score": 18
        }

    # =====================
    # DETAIL MODE (APIFY)
    # =====================
    try:
        images, captions = fetch_instagram_assets(username)
    except Exception as e:
        return {
            "status": "error",
            "username": username,
            "message": "Error obteniendo datos desde Instagram",
            "detail": str(e)
        }

    if not images or len(images) < 3:
        return {
            "status": "no_assets",
            "username": username,
            "message": "No se pudieron obtener suficientes imágenes",
            "scores": None,
            "total_score": None,
            "interpretation": None
        }

    analysis = analyze_with_gpt(images, captions)

    scores = analysis["scores"]
    total_score = sum(scores.values())

    return {
        "status": "ok",
        "username": username,
        "scores": scores,
        "total_score": total_score,
        "dominant_content_type": analysis["dominant_content_type"],
        "interpretation": analysis["interpretation"]
    }
