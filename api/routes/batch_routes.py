from fastapi import APIRouter, HTTPException, UploadFile, File, Form, status, BackgroundTasks, Depends, Request
from typing import Optional, Dict
import json
import traceback
import re

from api.core.auth import verify_admin_access
from api.models.trainee import BatchConfig, BatchTraineeCreate, BatchProcessingResponse
from api.services.batch_service import BatchService

router = APIRouter(prefix="/trainee", tags=["trainee"])

@router.post("/batch", response_model=BatchProcessingResponse)
async def process_batch( 
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    run_stage: str = Form("dev"),
    batch: Optional[str] = Form(""),
    role: str = Form("trainee"),
    group_id: Optional[str] = Form(None),
    delimiter: str = Form(","),
    encoding: str = Form("utf-8"),
    chunk_size: int = Form(20),
    is_mock: bool = Form(False),
    login_url: Optional[str] = Form(None),
    current_user: Dict = Depends(verify_admin_access)
):
    """
    Process a batch of trainees from a CSV file
    
    The CSV file should contain the following required columns:
    - name
    - email
    
    Optional columns:
    - nationality
    - gender
    - date_of_birth
    - vulnerable
    - bio
    - city_of_residence
    - status
    - other_info
    """
    
    try:
        # Check if current_user is an error response
        if isinstance(current_user, dict) and "success" in current_user and not current_user["success"]:
            return BatchProcessingResponse.error_response(
                error_type=current_user["error"]["error_type"],
                error_message=current_user["error"]["error_message"],
                error_location=current_user["error"]["error_location"],
                error_data=current_user["error"]["error_data"]
            )

        print("\n=== Batch Processing Request ===")
        print(f"User: {current_user['email']}")
        print(f"Batch: {batch}")
        print(f"File: {file.filename}")
        
        # Validate file
        if not file.filename:
            return BatchProcessingResponse.error_response(
                error_type="VALIDATION_ERROR",
                error_message="No file provided",
                error_location="file_validation",
                error_data={"filename": file.filename}
            )

        # Read and validate file content
        file_content = await file.read()
        print(f"File size: {len(file_content)} bytes")
        
        try:
            preview = file_content[:100].decode('utf-8')
            print(f"Content preview: {preview}")
        except UnicodeDecodeError:
            print("Note: File content is not UTF-8 decodable")
            
        # Extract origin from headers
        origin = request.headers.get('origin')
        if not origin:
            origin = request.headers.get('referer')
        if not origin:
            origin = 'https://dev-tenx.10academy.org'
        origin = origin.rstrip('/')
        actual_login_url = f"{origin}/login"

        # Validate login_url format
        if not re.match(r'^https?://', actual_login_url):
            return BatchProcessingResponse.error_response(
                error_type="VALIDATION_ERROR",
                error_message="login_url must be a valid HTTP(S) URL",
                error_location="login_url_validation",
                error_data={"login_url": actual_login_url}
            )
        
        # Use authenticated user's email as admin_email
        admin_email = current_user["email"]

        try:
            config = BatchConfig(
                run_stage=run_stage,
                batch=batch,
                role=role,
                group_id=group_id,
                is_mock=is_mock,
                delimiter=delimiter,
                encoding=encoding,
                chunk_size=chunk_size,
                login_url=actual_login_url,
                admin_email=admin_email
            )
            
        except Exception as config_error:
            return BatchProcessingResponse.error_response(
                error_type="VALIDATION_ERROR",
                error_message=f"Invalid configuration: {str(config_error)}",
                error_location="config_validation",
                error_data={"config_error": str(config_error)}
            )
        
        try:
            batch_create = BatchTraineeCreate(
                config=config,
                file_content=file_content
            )
            
        except Exception as batch_create_error:
            return BatchProcessingResponse.error_response(
                error_type="VALIDATION_ERROR",
                error_message=f"Error creating batch request: {str(batch_create_error)}",
                error_location="batch_create_validation",
                error_data={"batch_create_error": str(batch_create_error)}
            )
        
        # Create service instance
        batch_service = BatchService(batch_create)

        # Validate the FILE before saying yes.
        #
        # This used to queue the work and return 200 immediately, so a file that
        # could never succeed still produced "Batch processing started" on the
        # admin's screen. On 2026-09-19 a roster headed `Name,Email` was
        # rejected by the case-sensitive column check inside the background
        # task; the caller saw success, no trainees were created, and the only
        # trace was an email. "Started" is not a promise anyone can act on if it
        # is returned for work that has already failed.
        #
        # Only the cheap, deterministic checks run here — parse the file, check
        # the required columns, check for empty required cells. The slow part
        # (creating accounts, sending mail) stays in the background where it
        # belongs.
        validation_error = batch_service.validate_csv()
        if validation_error:
            return BatchProcessingResponse.error_response(
                error_type=validation_error.get("error_type", "VALIDATION_ERROR"),
                error_message=validation_error.get("error", "The CSV file could not be validated"),
                error_location="csv_validation",
                error_data={"batch": batch, **{k: v for k, v in validation_error.items() if k != "error"}},
                batch_info={"batch": batch, "admin_email": admin_email},
            )

        background_tasks.add_task(process_batch_background, batch_service)

        print("=== Starting Background Processing ===")

        return BatchProcessingResponse.success_response(
            message="Batch processing started",
            data={"status": "processing", "batch": batch},
            batch_info={"batch": batch, "admin_email": admin_email}
        )
        
    except HTTPException as http_error:
        print(f"HTTP Exception: {str(http_error)}")
        raise http_error
    except Exception as e:
        print(f"Unexpected error: {str(e)}")
        print(f"Traceback: {traceback.format_exc()}")
        return BatchProcessingResponse.error_response(
            error_type="INTERNAL_SERVER_ERROR",
            error_message=f"An unexpected error occurred: {str(e)}",
            error_location="unexpected_error",
            error_data={"error": str(e)}
        )

async def process_batch_background(service: BatchService):
    try:
        results = await service.process_batch_trainees()
        
        service.logger.info(
            "Batch processing completed",
            extra={
                'batch_id': service.config.batch,
                'total_processed': results.get('total_processed', 0),
                'successful': results.get('successful', 0),
                'failed': results.get('failed', 0),
                'status': results.get('status', 'unknown')
            }
        )
    except Exception as e:
        service.logger.error(
            "Batch processing failed",
            extra={
                'batch_id': service.config.batch,
                'error': str(e),
                'traceback': traceback.format_exc()
            }
        ) 