from fastapi import FastAPI
from App.api.routers import extract_router

app = FastAPI(title="PDF Text Extractor API")

app.include_router(extract_router.router, prefix="/api")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)