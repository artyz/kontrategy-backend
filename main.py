from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI()

# =========================
# CORS
# =========================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # luego lo cerramos
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================
# MODELS
# =========================
class VisualAnalysisRequest(BaseModel):
    username: str
    image_url: str | None = None

# =========================
# ROUTES
# =========================
@app.get("/")
def root():
    return {"status": "Kontrategy backend alive"}

@app.post("/analysis/visual")
def visual_analysis(data: VisualAnalysisRequest):
    """
    🔹 MOCK por ahora
    🔹 Luego aquí entra ChatGPT Vision
    """

    scores = {
        "paleta_colores": 4,
        "ruido_visual": 4,
        "consistencia_grafica": 5,
        "calidad_visual": 5,
        "presencia_humana": 4
    }

    total = sum(scores.values())

    return {
        "username": data.username,
        "scores": scores,
        "total_score": total,
        "interpretation": "Estética sólida y profesional con identidad clara."
    }
