from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from api.routes import trainee_routes, batch_routes, webhook_routes, env_routes
from api.core.error_handlers import validation_exception_handler, pydantic_validation_exception_handler
from typing import List

app = FastAPI(title="10 Academy User API")

# Add exception handlers
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(ValidationError, pydantic_validation_exception_handler)

# CORS Settings
# Additional allowed origins (for localhost development)
ADDITIONAL_ALLOWED_ORIGINS: List[str] = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:8000",
    "http://127.0.0.1:8000"
]
    
# Configure CORS with regex pattern to allow any subdomain of specified domains
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^https?://([\w\-]+\.)*?(10academy\.org|gettenacious\.com)(:\d+)?$",
    allow_origins=ADDITIONAL_ALLOWED_ORIGINS,  # Explicit localhost origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(trainee_routes.router)
app.include_router(batch_routes.router)
app.include_router(webhook_routes.router)
app.include_router(env_routes.router)

if __name__ == "__main__":
    import uvicorn
    # uvicorn.run("api.main:app", host="0.0.0.0", port=8113, reload=True) 
    uvicorn.run(app, host="0.0.0.0", port=8000) 