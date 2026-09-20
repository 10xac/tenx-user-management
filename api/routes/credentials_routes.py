from fastapi import APIRouter, Depends, Form
from typing import Dict, List, Optional
import json
import traceback

import requests

from api.core.auth import verify_admin_access
from api.core.logging_config import setup_logging
from review_scripts.strapi_methods import StrapiMethods

router = APIRouter(prefix="/trainee", tags=["trainee"])
logger = setup_logging()

# Set together, always. A correct password on an unconfirmed account still
# cannot log in - Strapi answers "Your account email is not confirmed" - so
# fixing only the password leaves the trainee exactly as stuck as before.
# Confirmed on 2026-09-20 against the live CMS: registering a user leaves
# confirmed=false, login is refused, and the same password works the moment
# confirmed flips to true.
CONFIRM_ON_RESET = True


def _find_user(sm: StrapiMethods, email: str) -> Optional[Dict]:
    response = requests.get(
        f"{sm.apiroot}/api/users",
        params={"filters[email][$eq]": email},
        headers={"Authorization": f"Bearer {sm.token}"},
        timeout=30,
    )
    if response.status_code != 200:
        return None
    rows = response.json()
    return rows[0] if isinstance(rows, list) and rows else None


@router.post("/credentials/reset")
async def reset_trainee_credentials(
    emails: str = Form(..., description="JSON array of trainee email addresses"),
    run_stage: str = Form("dev"),
    send_email: bool = Form(False, description="Also email each trainee their sign-in details"),
    login_url: Optional[str] = Form(None),
    current_user: Dict = Depends(verify_admin_access),
):
    """
    Set a trainee's password back to their own email address, and confirm the
    account, for a list of trainees at once.

    Why this exists. A bulk upload creates accounts whose password is the
    trainee's email, and then the welcome email that would tell them so is
    commented out in batch_service - so on 2026-09-19 thirty people were
    enrolled on Re-entry School and none of them could sign in or knew what
    their password was. Recovering that by hand meant a Strapi admin login,
    which most staff running a cohort do not have.

    `send_email` defaults to FALSE on purpose. Trainee email is switched off in
    this codebase with the note "not allowed to send emails to trainees", and
    turning a bulk endpoint into something that mails thirty real people
    because the default said so is not a decision this function gets to make.
    The caller has to ask for it.

    Setting a password to a value anyone can guess is a real weakening - it is
    the platform's existing default for bulk-created accounts, not an
    improvement on it. Trainees should be made to change it at first sign-in;
    that gate does not exist yet and is worth building.
    """
    if isinstance(current_user, dict) and "success" in current_user and not current_user["success"]:
        return {"success": False, "error": current_user.get("error")}

    try:
        wanted: List[str] = json.loads(emails)
        if not isinstance(wanted, list):
            raise ValueError("emails must be a JSON array")
    except Exception as exc:
        return {
            "success": False,
            "error": {"error_type": "VALIDATION_ERROR", "error_message": f"Could not read emails: {exc}"},
        }

    wanted = [str(e).strip().lower() for e in wanted if str(e).strip()]
    if not wanted:
        return {"success": False, "error": {"error_type": "VALIDATION_ERROR", "error_message": "No emails given"}}

    sm = StrapiMethods(run_stage=run_stage)
    done, failed = [], []

    for email in wanted:
        try:
            user = _find_user(sm, email)
            if not user:
                failed.append({"email": email, "reason": "No sign-in account exists for this address"})
                continue

            payload = {"password": email}
            if CONFIRM_ON_RESET:
                payload.update({"confirmed": True, "blocked": False})

            updated = requests.put(
                f"{sm.apiroot}/api/users/{user['id']}",
                json=payload,
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {sm.token}"},
                timeout=30,
            )
            if updated.status_code != 200:
                failed.append({"email": email, "reason": f"Update refused: {updated.status_code} {updated.text[:160]}"})
                continue

            # Prove it, rather than trust the 200. A PUT that stores a password
            # the user cannot then log in with is the failure this whole
            # endpoint exists to undo, and it would report success.
            check = requests.post(
                f"{sm.apiroot}/api/auth/local",
                json={"identifier": email, "password": email},
                timeout=30,
            )
            if check.status_code != 200:
                failed.append({
                    "email": email,
                    "reason": f"Password was set but sign-in still fails: {check.text[:160]}",
                })
                continue

            done.append({"email": email, "username": user.get("username")})

        except Exception as exc:
            logger.error("Credential reset failed", extra={"email": email, "error": str(exc)})
            failed.append({"email": email, "reason": str(exc)[:200]})

    emailed, email_failures = [], []
    if send_email and done:
        # Imported here so the endpoint still works on a host with no SES
        # credentials, as long as nobody asks it to send.
        from api.services.email_service import EmailService

        service = EmailService(source_email="train@10academy.org")
        target = (login_url or "https://tenx.gettenacious.com").rstrip("/") + "/login"
        for row in done:
            try:
                service.send_trainee_welcome_email(
                    email=row["email"], username=row["email"], password=row["email"], login_url=target,
                )
                emailed.append(row["email"])
            except Exception as exc:
                email_failures.append({"email": row["email"], "reason": str(exc)[:200]})

    logger.info("Trainee credentials reset", extra={
        "requested": len(wanted), "reset": len(done), "failed": len(failed),
        "emailed": len(emailed), "by": current_user.get("email"),
    })

    return {
        "success": len(failed) == 0,
        "message": f"{len(done)} of {len(wanted)} trainees can now sign in with their email as password",
        "data": {
            "reset": done,
            "failed": failed,
            "emailed": emailed,
            "email_failures": email_failures,
            "email_sending_requested": send_email,
        },
    }
