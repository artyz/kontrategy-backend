from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

class VisualAnalysisRequest(BaseModel):
    username: str
    image_url: str

@app.get("/")
def root():
    return {"status": "Kontrategy backend alive"}

@app.post("/analysis/visual")
def visual_analysis(data: VisualAnalysisRequest):
    # SIMULACIÓN (luego conectamos ChatGPT real)
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
