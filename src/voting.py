from typing import Optional, List

# import apiclient
from httplib2 import Http
from oauth2client import client, file, tools
from google.oauth2 import service_account
from oauth2client.service_account import ServiceAccountCredentials
import googleapiclient.discovery
import config

from nextcord import Message

import song_utils
from bust import BustController

# TODO: Eventually the function in this file should be rewritten not interact with
# Discord at all, and instead called by a wrapper in bust.py with most
# internal logic remaining here

def get_google_services():
    SCOPES = "https://www.googleapis.com/auth/drive"
    store = file.Storage(f"{config.auth_directory_filepath}/token.json")
    creds = store.get()
    if not creds or creds.invalid:
        flow = client.flow_from_clientsecrets(
           f"{config.auth_directory_filepath}/client_secrets.json", SCOPES
        )
        creds = tools.run_flow(flow, store)

    forms_service = googleapiclient.discovery.build(
        "forms",
        "v1",
        credentials=creds
    )

    drive_service = googleapiclient.discovery.build(
        "drive",
        "v3",
        credentials=creds
    )
    return forms_service, drive_service

def get_forms_service():
    """Return a forms service"""
    SCOPES = "https://www.googleapis.com/auth/forms.body"
    #DISCOVERY_DOC = "https://forms.googleapis.com/$discovery/rest?version=v1"
    #SERVICE_ACCOUNT_FILE = f"{config.auth_directory_filepath}/service_key.json"

    store = file.Storage(f"{config.auth_directory_filepath}/token.json")
    creds = store.get()
    if not creds or creds.invalid:
        flow = client.flow_from_clientsecrets(
           f"{config.auth_directory_filepath}/client_secrets.json", SCOPES
        )
        creds = tools.run_flow(flow, store)

        #creds = ServiceAccountCredentials.from_json_keyfile_name(
        #    SERVICE_ACCOUNT_FILE, SCOPES
        #)

    forms_service = googleapiclient.discovery.build(
        "forms",
        "v1",
        credentials=creds
        # http=creds.authorize(Http()),
        # discoveryServiceUrl=DISCOVERY_DOC,
        # static_discovery=False,
    )
    return forms_service


def create_remote_form(
    title: str,
    items: List[str],
    low_val: int,
    high_val: int,
    low_label: str,
    high_label: str,
    image: Optional[str] = None,
) -> str:

    form_info = {
        "info": {
            "title": title,
        }
    }

    # create question update request
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
                                }
                            }
                        },
                    },
                    "location": {"index": idx},
                }
            }
            for idx, title in enumerate(items)
        ]
    }

    # add image if exists
    if image:
        form_update["requests"].append(
            {
                "imageItem": {
                    "image": {
                        "altText": "It's bust time, baby.",
                        "sourceUri": image,
                    }
                }
            }
        )

    # get form service
    form_service, drive_service = get_google_services()

    # Creates the initial form
    form = form_service.forms().create(body=form_info).execute()
    print(form['formId'])

    # Add the video to the form
    form_service.forms().batchUpdate(formId=form["formId"], body=form_update).execute()

    # Print the result to see it now has a video
    result = form_service.forms().get(formId=form["formId"]).execute()

    return result["responderUri"]


# TODO: move this to bust.py
async def generate_form(
    bc: BustController, message: Message, image_link: Optional[str] = None
) -> None:
    command_success = "\N{THUMBS UP SIGN}"
    await message.add_reaction(command_success)

    # Extract bust number from channel name
    bust_number = "".join([c for c in bc.current_channel.name if c.isdigit()])
    if bust_number:
        bust_number = bust_number + " "

    song_list = [
        '"{}: {}"'.format(
            submit_message.author.display_name,
            song_utils.song_format(local_filepath, attachment.filename),
        )
        for submit_message, attachment, local_filepath in bc.current_channel_content
    ]

    form_url = create_remote_form(
        f"Busty's {bust_number}Voting",
        song_list,
        0,
        7,
        "OK",
        "Masterpiece",
        image_link,
    )
    await message.channel.send(form_url)
