from pydantic_settings import BaseSettings
from functools import lru_cache
from typing import Optional
import os
class Settings(BaseSettings):
    """Application settings"""
    APP_NAME: str = "10 Academy Trainee API"
    # API_V1_STR: str = "/api/v1"
    
    # CORS settings
    BACKEND_CORS_ORIGINS: list[str] = ["*"]
    
    # Default values
    RUN_STAGE: str = "dev"
    DEFAULT_ROLE: str = "trainee"
    DEFAULT_BATCH_SIZE: int = 20
    
    # File processing
    MAX_FILE_SIZE: int = 10 * 1024 * 1024  # 10MB
    ALLOWED_FILE_TYPES: list[str] = ["text/csv"]
    DEFAULT_ENCODING: str = "utf-8"
    DEFAULT_DELIMITER: str = ","
    
    # Required columns for batch processing
    REQUIRED_COLUMNS: list[str] = [
        "name",
        "email",
    
    ]
    
    class Config:
        case_sensitive = True
        env_file = ".env"



strapi_stage =  os.environ.get('STRAPI_STAGE','unknown')
print(f'Using STRAPI_STAGE={strapi_stage}')

def get_strapi_params(stage):
    if stage.lower().startswith('devapply'):
        root='dev-apply-cms'
        ssmkey="APPLY_DEV_STRAPI_TOKEN"
    elif stage.lower().startswith('carisurg_apply'):
        root='apply-carisurg-cms'
        ssmkey="CARISURG_APPLY_PROD_STRAPI_TOKEN"
    elif stage.lower().startswith('carisurg'):
        root='carisurg-cms'
        ssmkey="CARISURG_PROD_STRAPI_TOKEN"
    elif stage.lower().startswith('apply'):
        root='apply-cms'
        ssmkey="APPLY_PROD_STRAPI_TOKEN" 
    elif stage.lower().startswith('devu2j'):
        root='dev-u2jcms'#'dev-u2j-cms'
        ssmkey="U2J_DEV_STRAPI_TOKEN" 
    elif stage.lower().startswith('u2j'):
        root='u2jcms'
        ssmkey="U2J_PROD_STRAPI_TOKEN"
    elif stage.lower().startswith('kaim'):
        root='kaimcms'
        ssmkey="KAIM_PROD_STRAPI_TOKEN"
    elif stage.lower().startswith('kepler'):
        root='keplercms'
        ssmkey="KEPLER_PROD_STRAPI_TOKEN" 

    elif stage.lower().startswith('prod'):
        root='cms'
        ssmkey="TENX_PROD_STRAPI_TOKEN" 
    elif stage.lower().startswith('tenacious'):
        root='tenaciouscms'
        ssmkey="TENACIOUS_PROD_STRAPI_TOKEN"
    elif stage.lower().startswith('simulation'):
        root='simulation-cms'
        ssmkey="TENX_SIMULATION_STRAPI_TOKEN"
    elif stage.lower().startswith('demo'):
        root='democms'
        ssmkey="DEMO_PROD_STRAPI_TOKEN"
    elif stage.lower().startswith('shared'):
        root='sharedcms'
        ssmkey="SHARED_PROD_STRAPI_TOKEN"
    else:  
        root='dev-cms'
        ssmkey="TENX_DEV_STRAPI_TOKEN"  

    return root, ssmkey   
    
root, ssmkey = get_strapi_params(strapi_stage)

@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance"""
    return Settings() 