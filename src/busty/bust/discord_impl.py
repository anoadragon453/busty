"""Discord implementations of BustController protocols."""

import random
from io import BytesIO
from typing import TYPE_CHECKING

from discord import Embed, File, Message, TextChannel

from busty import discord_utils, song_utils
from busty.config import constants
from busty.config.settings import BustySettings
from busty.track import Track

if TYPE_CHECKING:
    from busty.main import BustyBot


class DiscordBustOutput:
    """Discord implementation of BustOutput protocol."""

    def __init__(
        self, channel: TextChannel, client: "BustyBot", settings: BustySettings
    ):
        self.channel = channel
        self.client = client
        self.settings = settings
        self._now_playing_msg: Message | None = None

    async def send_bust_started(self) -> None:
        """Notify users that the bust session is beginning."""
        await self.channel.send("Let's get **BUSTY**.")

    async def send_cooldown_notice(self) -> None:
        """Display a notice during the cooldown period before a track plays."""
        embed = Embed(
            title="Currently Chilling",
            description="The track will start soon...\n\n**REMEMBER TO VOTE ON THE GOOGLE FORM!**",
        )
        await self.channel.send(embed=embed)

    async def display_now_playing(
        self,
        track: Track,
        cover_art_data: bytes | None,
    ) -> None:
        """Update all UI elements to show the track is now playing."""
        # Choose random emoji for display
        random_emoji = random.choice(self.settings.emoji_list)

        # Build "Now Playing" embed
        embed = song_utils.embed_song(track, random_emoji)

        # Send embed with cover art if available
        if cover_art_data:
            # Convert bytes to Discord File
            image_fp = BytesIO(cover_art_data)
            cover_art_file = File(image_fp, filename="cover.jpg")
            embed.set_image(url=f"attachment://{cover_art_file.filename}")
            self._now_playing_msg = await self.channel.send(
                file=cover_art_file, embed=embed
            )
        else:
            self._now_playing_msg = await self.channel.send(embed=embed)

        # Pin the message
        await discord_utils.try_set_pin(self._now_playing_msg, True)

        # Update bot nickname to show current track
        new_nick = f"{random_emoji}{track.formatted_title}"
        await self.set_bot_nickname(new_nick)

    async def unpin_now_playing(self) -> None:
        """Unpin the currently pinned now-playing message."""
        if self._now_playing_msg:
            await discord_utils.try_set_pin(self._now_playing_msg, False)
            self._now_playing_msg = None

    async def send_bust_finished(self, total_duration: float) -> None:
        """Notify users that the bust session has completed."""
        goodbye_emoji = ":heart_on_fire:"
        embed = Embed(
            title=f"{goodbye_emoji} That's it everyone {goodbye_emoji}",
            description=(
                "Hope ya had a good **BUST!**\n"
                f"*Total length of all submissions: {song_utils.format_time(int(total_duration))}*"
            ),
            color=constants.LIST_EMBED_COLOR,
        )
        await self.channel.send(embed=embed)

    async def get_bot_nickname(self) -> str | None:
        """Get the bot's current display nickname."""
        if not self.client.user or not self.channel.guild:
            return None

        bot_member = self.channel.guild.get_member(self.client.user.id)
        return bot_member.display_name if bot_member else None

    async def set_bot_nickname(self, nickname: str | None) -> None:
        """Set the bot's display nickname."""
        if not self.client.user or not self.channel.guild:
            return

        bot_member = self.channel.guild.get_member(self.client.user.id)
        if not bot_member:
            return

        # Truncate to Discord's limit if nickname provided
        if nickname and len(nickname) > constants.NICKNAME_CHAR_LIMIT:
            nickname = nickname[: constants.NICKNAME_CHAR_LIMIT - 1] + "…"

        await bot_member.edit(nick=nickname)
