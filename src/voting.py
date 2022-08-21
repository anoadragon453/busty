import re
from typing import Optional

from nextcord import Message

import bust
import config
import song_utils

# TODO: Eventually the function in this file should be rewritten not interact with
# Discord at all, and instead called by a wrapper in bust.py with most
# internal logic remaining here


async def generate_form(
    message: Message, google_drive_image_link: Optional[str] = None
) -> None:
    # Escape strings so they can be assigned as literals within appscript
    def escape_appscript(text: str) -> str:
        return text.replace("\\", "\\\\").replace('"', '\\"')

    # Extract bust number from channel name
    bust_number = "".join([c for c in bust.current_channel.name if c.isdigit()])
    if bust_number:
        bust_number = bust_number + " "

    # Constants in generated code, Make sure these strings are properly escaped
    form_title = f"Busty's {bust_number}Voting"
    low_string = "OK"
    high_string = "Masterpiece"
    low_score = 0
    high_score = 7

    appscript = "function r(){"
    # Setup and grab form
    appscript += f'var f=FormApp.create("{form_title}");'
    # Add questions to form
    appscript += "[" + ",".join(
        [
            '"{}: {}"'.format(
                escape_appscript(submit_message.author.display_name),
                escape_appscript(
                    song_utils.song_format(local_filepath, attachment.filename)
                ),
            )
            for submit_message, attachment, local_filepath in bust.current_channel_content
        ]
    )
    appscript += (
        "].forEach((s,i)=>f.addScaleItem()"
        '.setTitle(i+1+". "+s)'
        f".setBounds({low_score},{high_score})"
        f'.setLabels("{low_string}","{high_string}")'
        ".setRequired(true)"
        ")"
    )

    if google_drive_image_link:
        # Extract image file ID from the passed link
        file_id_matches = re.match(
            r"https://drive.google.com/file/d/(.+)/view", google_drive_image_link
        )
        if file_id_matches:
            file_id = file_id_matches.group(1)

            # Add an image to the form
            appscript += (
                f';f.addImageItem().setImage(DriveApp.getFileById("{file_id}"))'
            )

    # Add comments/suggestions to form
    appscript += ";f.addParagraphTextItem().setTitle('Comments/suggestions')"

    # Print links to the form
    appscript += (
        ';console.log("Edit: "+f.getEditUrl()+"\\n\\nPublished: "+f.getPublishedUrl());'
    )

    # Close appscript main function
    appscript += "}"
    # There is no way to escape ``` in a code block on Discord, so we replace ``` --> '''
    appscript = appscript.replace("```", "'''")

    # Print message in chunks respecting character limit
    chunk_size = config.MESSAGE_LIMIT - 9
    for i in range(0, len(appscript), chunk_size):
        await message.channel.send("```js\n{}```".format(appscript[i : i + chunk_size]))

    # Tell the user how to generate the form
    await message.channel.send(
        "Copy/paste the above code into a new appscript project (replace anything already there). "
        "Then click Save, and Run: https://script.google.com/home/projects/create\n\n"
        "Authorize the project to use your Google Account when prompted. Click Advanced -> Go to ..."
    )
