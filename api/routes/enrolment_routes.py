from fastapi import APIRouter, Depends, Form
from typing import Dict, List, Optional
import json

from api.core.auth import verify_admin_access
from api.core.logging_config import setup_logging
from api.models.trainee import TraineeCreate, ConfigInfo, TraineeInfo
from api.services.trainee_service import TraineeService
from review_scripts.strapi_graphql import StrapiGraphql
from review_scripts.communication_manager import CommunicationManager

router = APIRouter(prefix="/trainee", tags=["trainee"])
logger = setup_logging()


@router.get("/enrolable")
async def list_enrolable_trainees(
    run_stage: str = "dev",
    exclude_batch: Optional[str] = None,
    current_user: Dict = Depends(verify_admin_access),
):
    """
    Trainees that already exist, so a cohort can be filled from people the
    platform already knows rather than from a CSV every time.

    `exclude_batch` drops anyone already on that cohort, because the useful
    question when adding to Re-entry School is "who is NOT already here".
    """
    if isinstance(current_user, dict) and "success" in current_user and not current_user["success"]:
        return {"success": False, "error": current_user.get("error")}

    sg = StrapiGraphql(run_stage=run_stage)
    query = """
      query {
        trainees(pagination: { limit: 1000 }) {
          data {
            id
            attributes {
              email
              trainee_batch_accesses {
                data { attributes { batch { data { id attributes { Batch } } } } }
              }
              all_user { data { id attributes { name } } }
            }
          }
        }
      }
    """
    result = sg.Select_from_table(query=query, variables={})
    rows = (result or {}).get("data", {}).get("trainees", {}).get("data", []) or []

    people = []
    for row in rows:
        attrs = row.get("attributes", {}) or {}
        accesses = ((attrs.get("trainee_batch_accesses") or {}).get("data") or [])
        cohorts = []
        for access in accesses:
            batch = (((access.get("attributes") or {}).get("batch") or {}).get("data")) or {}
            if batch:
                cohorts.append({"id": batch.get("id"), "name": (batch.get("attributes") or {}).get("Batch")})
        if exclude_batch and any(str(c["id"]) == str(exclude_batch) for c in cohorts):
            continue
        all_user = ((attrs.get("all_user") or {}).get("data")) or {}
        people.append({
            "trainee_id": row.get("id"),
            "email": attrs.get("email"),
            "name": (all_user.get("attributes") or {}).get("name") or "",
            "cohorts": cohorts,
        })

    people.sort(key=lambda p: (p.get("name") or p.get("email") or "").lower())
    return {"success": True, "data": {"trainees": people, "count": len(people)}}


@router.post("/enrol")
async def enrol_existing_trainees(
    emails: str = Form(..., description="JSON array of existing trainee emails"),
    batch: str = Form(..., description="Target cohort id"),
    run_stage: str = Form("dev"),
    group_id: Optional[str] = Form(None),
    current_user: Dict = Depends(verify_admin_access),
):
    """
    Add trainees who already exist to another cohort.

    This goes through TraineeService.create_trainee_services, which recognises
    an existing trainee and takes its existing-trainee branch, rather than
    writing the membership here. That branch is the only code that updates BOTH
    stores cohort membership lives in:

        trainee_batch_accesses   grants the trainee access to the cohort
        allUser batch / groups   is what the trainee lists actually filter on

    Writing only the first is a long-standing trap here: access is granted, the
    person can open the cohort, and they appear in none of the staff-facing
    lists - so they look enrolled to themselves and missing to everyone else.
    Reusing the branch means this endpoint cannot drift from it.
    """
    if isinstance(current_user, dict) and "success" in current_user and not current_user["success"]:
        return {"success": False, "error": current_user.get("error")}

    try:
        wanted: List[str] = json.loads(emails)
        if not isinstance(wanted, list):
            raise ValueError("emails must be a JSON array")
    except Exception as exc:
        return {"success": False, "error": {"error_type": "VALIDATION_ERROR", "error_message": str(exc)}}

    wanted = [str(e).strip().lower() for e in wanted if str(e).strip()]
    if not wanted:
        return {"success": False, "error": {"error_type": "VALIDATION_ERROR", "error_message": "No emails given"}}

    sg = StrapiGraphql(run_stage=run_stage)
    cm = CommunicationManager()
    enrolled, failed, skipped = [], [], []

    for email in wanted:
        try:
            existing = cm.read_trainee_by_email(sg, email).get("data", {}).get("trainees", {}).get("data", [])
            if not existing:
                # Deliberately not created here. This endpoint adds people the
                # platform already has; creating one silently would make a
                # typo'd address into a new trainee record nobody asked for.
                skipped.append({"email": email, "reason": "No existing trainee with this email - use the CSV upload to create one"})
                continue

            name = ""
            all_user = (((existing[0].get("attributes") or {}).get("all_user") or {}).get("data")) or {}
            name = (all_user.get("attributes") or {}).get("name") or email.split("@")[0]

            trainee_create = TraineeCreate(
                config=ConfigInfo(
                    run_stage=run_stage, batch=str(batch), role="trainee",
                    group_id=group_id or "", is_mock=False,
                    login_url="https://tenx.gettenacious.com",
                ),
                trainee=TraineeInfo(
                    name=name, email=email, password=email, status="Accepted",
                    nationality="", gender="", date_of_birth=None, vulnerable="",
                    city_of_residence="", bio="", other_info={},
                ),
            )
            result = TraineeService(trainee_create).create_trainee_services()
            if result.get("success"):
                enrolled.append({"email": email, "name": name})
            else:
                error = result.get("error") or {}
                failed.append({
                    "email": email,
                    "reason": error.get("error_message") or error.get("message") or "No reason reported",
                })
        except Exception as exc:
            logger.error("Enrolment failed", extra={"email": email, "batch": batch, "error": str(exc)})
            failed.append({"email": email, "reason": str(exc)[:200]})

    logger.info("Enrolled existing trainees", extra={
        "batch": batch, "requested": len(wanted), "enrolled": len(enrolled),
        "skipped": len(skipped), "failed": len(failed), "by": current_user.get("email"),
    })

    return {
        "success": len(failed) == 0,
        "message": f"{len(enrolled)} of {len(wanted)} trainees added to cohort {batch}",
        "data": {"enrolled": enrolled, "skipped": skipped, "failed": failed},
    }
