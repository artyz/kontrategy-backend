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
    mode: str = "summary"  # summary | detail
    images: Optional[List[str]] = None
    captions: Optional[List[str]] = None

# =====================
# GPT ANALYSIS
# =====================
def analyze_with_gpt(images: list[str], captions: list[str]) -> dict:
    """
    Análisis visual + semántico basado en thumbnails + contexto textual.
    """

    prompt = f"""
Analiza el LOOK & FEEL de un perfil de Instagram basándote en:

1. Thumbnails de los últimos posts
2. Contexto textual (títulos y descripciones)

Evalúa:
- Paleta de colores
- Consistencia visual
- Ruido visual
- Calidad gráfica
- Presencia humana
- Tipo de contenido dominante (educativo, entretenimiento, promocional)

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
    mode = data.mode

    if raw.startswith("http"):
        username = raw.rstrip("/").split("/")[-1]
    else:
        username = raw.replace("@", "").replace("/", "").lower()

    # =====================
    # SUMMARY MODE (dashboard)
    # =====================
    if mode == "summary":
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
    # DETAIL MODE (assets desde frontend)
    # =====================
    if not data.images or len(data.images) < 3:
        return {
            "status": "no_assets",
            "username": username,
            "message": "No se recibieron suficientes imágenes desde el frontend",
            "scores": None,
            "total_score": None,
            "interpretation": None
        }

    captions = data.captions or []

    analysis = analyze_with_gpt(data.images, captions)

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
