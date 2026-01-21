import logging
from pathlib import Path

import googleapiclient.discovery
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import Resource

logger = logging.getLogger(__name__)


def get_google_services(
    google_auth_file: Path,
) -> tuple[Resource | None, Resource | None]:
    """Get Google Forms and Drive services using a service account.

    Args:
        google_auth_file: Path to the service account key file.

    Returns:
        Tuple of (forms_service, drive_service), or (None, None) if auth fails.
    """
    SCOPES = ["https://www.googleapis.com/auth/drive"]

    try:
        creds = Credentials.from_service_account_file(
            str(google_auth_file), scopes=SCOPES
        )
    except Exception as e:
        if isinstance(e, FileNotFoundError):
            error_msg = f"Could not find {google_auth_file}"
        else:
            error_msg = (
                f"Encountered {type(e).__name__} reading {google_auth_file}: {e}"
            )
        logger.error(f"{error_msg}. Skipping form generation")
        return None, None

    forms_service = googleapiclient.discovery.build("forms", "v1", credentials=creds)
    drive_service = googleapiclient.discovery.build("drive", "v3", credentials=creds)
    return forms_service, drive_service


def create_remote_form(
    title: str,
    items: list[str],
    low_val: int,
    high_val: int,
    low_label: str,
    high_label: str,
    google_auth_file: Path,
    google_form_folder: str | None,
    image_url: str | None = None,
) -> str | None:
    """Create a Google Form for voting.

    Args:
        title: Form title.
        items: List of items to rate.
        low_val: Minimum rating value.
        high_val: Maximum rating value.
        low_label: Label for low rating.
        high_label: Label for high rating.
        google_auth_file: Path to the service account key file.
        google_form_folder: Google Drive folder ID to move form to, or None.
        image_url: Optional image URL to include at top of form.

    Returns:
        Form URL if successful, None otherwise.
    """
    form_info = {
        "info": {
            "title": title,
            "document_title": title,
        }
    }

    form_update = {
        "requests": [
            {
                "createItem": {
                    "item": {
                        "title": title,
                        "questionItem": {
                            "question": {
                                "scaleQuestion": {
                                    "low": low_val,
                                    "high": high_val,
                                    "lowLabel": low_label,
                                    "highLabel": high_label,
                                },
                                "required": True,
                            }
                        },
                    },
                    "location": {"index": idx},
                }
            }
            for idx, title in enumerate(items)
        ]
        + [
            {
                "createItem": {
                    "item": {
                        "title": "Comments/Suggestions/Jokes",
                        "questionItem": {
                            "question": {
                                "textQuestion": {
                                    "paragraph": True,
                                }
                            }
                        },
                    },
                    "location": {"index": len(items)},
                }
            }
        ]
    }

    # get form service
    form_service, drive_service = get_google_services(google_auth_file)
    if form_service is None or drive_service is None:
        return None

    # Creates the initial form
    forms = form_service.forms()
    form_info = forms.create(body=form_info).execute()
    form_id = form_info["formId"]
    form_url = str(form_info["responderUri"])

    # Add content to the form
    forms.batchUpdate(formId=form_id, body=form_update).execute()

    # Prepend image in separate update in case it fails
    if image_url:
        try:
            image_update = {
                "requests": [
                    {
                        "createItem": {
                            "item": {
                                "imageItem": {
                                    "image": {
                                        "altText": "It's bust time, baby.",
                                        "sourceUri": image_url,
                                    }
                                }
                            },
                            "location": {"index": 0},
                        }
                    }
                ]
            }
            forms.batchUpdate(formId=form_id, body=image_update).execute()
        except Exception as e:
            logger.error(f"Error adding image to form: {e}")

    # Move form to correct folder + rename
    if google_form_folder:
        files = drive_service.files()
        file = files.get(
            fileId=form_id, fields="capabilities/canMoveItemWithinDrive, parents"
        ).execute()
        if file["capabilities"]["canMoveItemWithinDrive"]:
            file_parent_id = file["parents"][0]
            try:
                files.update(
                    fileId=form_id,
                    removeParents=file_parent_id,
                    addParents=google_form_folder,
                ).execute()
            except Exception as e:
                logger.error(f"Error moving form: {e}")

    return form_url
