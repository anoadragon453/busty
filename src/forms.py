from typing import List, Optional, Tuple

import googleapiclient.discovery
from googleapiclient.discovery import Resource
from oauth2client.service_account import ServiceAccountCredentials

import config


def get_google_services() -> Tuple[Optional[Resource], Optional[Resource]]:
    SCOPES = "https://www.googleapis.com/auth/drive"

    try:
        creds = ServiceAccountCredentials.from_json_keyfile_name(
            config.google_auth_file, SCOPES
        )
    except Exception as e:
        if isinstance(e, FileNotFoundError):
            error_msg = f"Could not find {config.google_auth_file}"
        else:
            error_msg = (
                f"Encountered {type(e).__name__} reading {config.google_auth_file}"
            )
        print(f"{error_msg}. Skipping form generation...")
        return None, None

    forms_service = googleapiclient.discovery.build("forms", "v1", credentials=creds)
    drive_service = googleapiclient.discovery.build("drive", "v3", credentials=creds)
    return forms_service, drive_service


def create_remote_form(
    title: str,
    items: List[str],
    low_val: int,
    high_val: int,
    low_label: str,
    high_label: str,
    image_url: Optional[str] = None,
) -> Optional[str]:

    form_info = {
        "info": {
            "title": title,
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
                                "required": True
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
    form_service, drive_service = get_google_services()
    if form_service is None or drive_service is None:
        return None

    # Creates the initial form
    forms = form_service.forms()
    form_info = forms.create(body=form_info).execute()
    form_id = form_info["formId"]
    form_url = form_info["responderUri"]

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
            print("Error adding image to form: ", e)

    # Move form to correct folder + rename
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
                addParents=config.google_form_folder,
                body={"name": title},
            ).execute()
        except Exception as e:
            print("Error moving form:", e)

    return form_url
