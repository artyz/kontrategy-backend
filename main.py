import os
import json
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, constr
from typing import List, Optional
from openai import OpenAI

# =====================
# ENV
# =====================
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY missing")

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
    mode: str = "summary"
    images: Optional[List[str]] = None
    captions: Optional[List[str]] = None

# =====================
# HELPERS
# =====================
def filter_valid_images(images: List[str]) -> List[str]:
    valid = []
    for img in images:
        img_lower = img.lower()
        if any(ext in img_lower for ext in [".jpg", ".jpeg", ".png", ".webp"]) \
           and not any(bad in img_lower for bad in ["googlelogo", "gstatic", "logo", "sprite", ".gif", ".svg"]):
            valid.append(img)
    return valid[:10]  # límite seguro para GPT

# =====================
# GPT ANALYSIS
# =====================
def analyze_with_gpt(images: List[str], captions: List[str]) -> dict:
    prompt = f"""
Analiza el LOOK & FEEL de un perfil de Instagram basándote en:

1. Thumbnails de posts reales
2. Contexto textual

Evalúa:
- Paleta de colores
- Consistencia visual
- Ruido visual
- Calidad gráfica
- Presencia humana
- Tipo de contenido dominante

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
  "interpretation": "Análisis profesional breve"
}}
"""

    response = client.chat.completions.create(
        model="gpt-4o",
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "user",
                "content": (
                    [{"type": "text", "text": prompt}]
                    + [{"type": "image_url", "image_url": {"url": img}} for img in images]
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
    username = data.username.strip().replace("@", "").replace("/", "").lower()

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

    if not data.images:
        return {
            "status": "no_assets",
            "message": "No se recibieron imágenes desde el frontend"
        }

    images = filter_valid_images(data.images)

    if len(images) < 3:
        return {
            "status": "no_assets",
            "message": "Imágenes insuficientes o inválidas para análisis"
        }

    captions = data.captions or []

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
