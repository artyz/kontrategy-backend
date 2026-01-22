import os
import json
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, constr
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

# =====================
# MOCK DATA (temporal)
# luego será reemplazado por Google results reales
# =====================
def get_mock_assets(username: str):
    """
    Simula los últimos 15 posts del perfil
    usando thumbnails + captions públicas.
    """
    images = [
        f"https://example.com/{username}/thumb_{i}.jpg"
        for i in range(1, 16)
    ]

    captions = [
        "Post educativo con texto sobre imagen",
        "Video con presentador hablando a cámara",
        "Gráfico con branding fuerte",
        "Contenido promocional",
        "Post inspiracional minimalista",
    ] * 3

    return images[:15], captions[:15]

# =====================
# GPT ANALYSIS
# =====================
def analyze_with_gpt(images: list[str], captions: list[str]) -> dict:
    """
    Análisis visual SEMÁNTICO.
    NO necesita screenshot real.
    """
    prompt = f"""
Eres un estratega visual senior especializado en Instagram.

Tienes un GRID SIMULADO 3x5 (15 posts).

IMÁGENES (thumbnails públicas):
{json.dumps(images, indent=2)}

TEXTOS / DESCRIPCIONES:
{json.dumps(captions, indent=2)}

Analiza el LOOK & FEEL del perfil considerando:
- Paleta de colores dominante
- Consistencia gráfica
- Ruido visual
- Calidad visual
- Presencia humana
- Uso de texto sobre imagen
- Repetición de formatos

Devuelve SOLO JSON válido con este formato EXACTO:

{{
  "scores": {{
    "paleta_colores": 1,
    "ruido_visual": 1,
    "consistencia_grafica": 1,
    "calidad_visual": 1,
    "presencia_humana": 1
  }},
  "interpretation": "Análisis visual profesional breve"
}}
"""

    response = client.chat.completions.create(
        model="gpt-4o",
        response_format={"type": "json_object"},
        messages=[{"role": "user", "content": prompt}],
        max_tokens=400
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

    username = (
        raw.replace("https://www.instagram.com/", "")
        .replace("@", "")
        .replace("/", "")
        .lower()
    )

    # 🔹 Paso 1: obtener assets (mock por ahora)
    images, captions = get_mock_assets(username)

    # 🔹 Paso 2: análisis visual semántico
    analysis = analyze_with_gpt(images, captions)

    scores = analysis["scores"]
    total_score = sum(scores.values())

    return {
        "status": "ok",
        "username": username,
        "scores": scores,
        "total_score": total_score,
        "interpretation": analysis["interpretation"],
    }
