from fastapi import FastAPI

app = FastAPI(title="Waterpolo Fantasy API")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
