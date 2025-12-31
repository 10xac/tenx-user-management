from fastapi import APIRouter, Depends, HTTPException, status
from api.core.auth import verify_admin_access
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
import logging

from utils.secret import (
    force_refresh_secrets,
    get_cache_metadata,
    get_all_secrets,
    mask_secret_value,
    clear_api_key_cache,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/env", tags=["environment"])


# =============================================================================
# Request/Response Models
# =============================================================================

class EnvRefreshRequest(BaseModel):
    """Request model for refreshing environment variables."""
    key: Optional[str] = Field(None, description="Specific key to return (masked). If None, returns all keys masked.")
    sname: str = Field("tenx/env/vars", description="Secret name in AWS Secrets Manager")
    run_stage: str = Field("dev", description="Run stage for context (e.g., prod, dev)")


class EnvCheckRequest(BaseModel):
    """Request model for checking cache status."""
    key: Optional[str] = Field(None, description="Specific key to check (masked value returned)")
    sname: str = Field("tenx/env/vars", description="Secret name to check cache for")
    run_stage: str = Field("dev", description="Run stage for context (e.g., prod, dev)")


class EnvRefreshResponse(BaseModel):
    """Response model for refresh operation."""
    success: bool
    message: str
    secrets_count: int
    requested_key: Optional[str] = None
    masked_value: Optional[str] = None
    masked_secrets: Optional[Dict[str, str]] = None
    api_key_cache_cleared: bool = False
    errors: Optional[list] = None


class EnvCheckResponse(BaseModel):
    """Response model for cache check operation."""
    success: bool
    cache_metadata: Dict[str, Any]
    requested_key: Optional[str] = None
    masked_value: Optional[str] = None
    sample_keys: Optional[list] = None


# =============================================================================
# Endpoints
# =============================================================================

@router.post("/refresh_env_vars", response_model=EnvRefreshResponse)
async def refresh_env_vars(
    request: EnvRefreshRequest,
    _: Dict = Depends(verify_admin_access)
):
    """
    Force refresh secrets from AWS Secrets Manager.
    
    - Clears memory and file cache
    - Fetches fresh secrets from AWS
    - Updates os.environ with new values
    - Clears get_api_key lru_cache
    
    Returns masked values only (never raw secrets).
    """
    errors = []
    
    try:
        # Force refresh secrets (clears cache, fetches from AWS)
        secrets = force_refresh_secrets(sname=request.sname)
        
        # Clear API key cache
        api_cache_cleared = clear_api_key_cache()
        
        # Build response
        response_data = {
            "success": True,
            "message": f"Successfully refreshed {len(secrets)} secrets from {request.sname}",
            "secrets_count": len(secrets),
            "api_key_cache_cleared": api_cache_cleared,
        }
        
        # If specific key requested, return its masked value
        if request.key:
            response_data["requested_key"] = request.key
            if request.key in secrets:
                response_data["masked_value"] = mask_secret_value(secrets[request.key])
            else:
                response_data["masked_value"] = "<not found>"
                errors.append(f"Key '{request.key}' not found in secrets")
        else:
            # Return all keys with masked values
            response_data["masked_secrets"] = {
                k: mask_secret_value(v) for k, v in secrets.items()
            }
        
        if errors:
            response_data["errors"] = errors
            
        return EnvRefreshResponse(**response_data)
        
    except Exception as e:
        logger.error(f"Failed to refresh env vars: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to refresh secrets: {str(e)}"
        )


@router.post("/check_env_cache", response_model=EnvCheckResponse)
def check_env_cache(
    request: EnvCheckRequest,
    _: Dict = Depends(verify_admin_access)
):
    """
    Check the status of the secrets cache.
    
    Returns metadata about memory and file cache:
    - Whether cache exists
    - Cache age in seconds
    - Whether cache is fresh (within TTL)
    - Number of keys in cache
    
    Optionally returns masked value for a specific key.
    """
    try:
        # Get cache metadata
        metadata = get_cache_metadata(sname=request.sname)
        
        response_data = {
            "success": True,
            "cache_metadata": metadata,
        }
        secrets = None
        try:
            secrets = get_all_secrets(sname=request.sname)
        except Exception as e:
            logger.error(f"Failed to fetch secrets for cache check: {e}")
        
        # If specific key requested, try to get its masked value from cache
        if request.key:
            response_data["requested_key"] = request.key
            try:
                if secrets is None:
                    raise Exception("Secrets unavailable for requested key lookup")
                if request.key in secrets:
                    response_data["masked_value"] = mask_secret_value(secrets[request.key])
                else:
                    response_data["masked_value"] = "<not found>"
            except Exception as e:
                logger.error(
                    "Failed to retrieve masked value for key %s in %s",
                    request.key,
                    request.sname,
                )
                response_data["masked_value"] = "<unavailable>"
        
        # Include sample keys (first 10, just the key names)
        try:
            if secrets is None:
                raise Exception("Secrets unavailable for sample keys retrieval")
            response_data["sample_keys"] = list(secrets.keys())[:10]
        except Exception as e:
            logger.error(
                "Failed to build sample keys list for %s", request.sname
            )
        
        return EnvCheckResponse(**response_data)
        
    except Exception as e:
        logger.error(f"Failed to check env cache: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to check cache: {str(e)}"
        )
