"""Shared test fixtures and utilities."""

import logging
from pathlib import Path

import pytest

from busty.config.settings import BustySettings
from busty.track import Track
from tests.mocks.mock_audio import MockAudioPlayer
from tests.mocks.mock_output import MockAIService, MockBustOutput, MockUserPreferences


@pytest.fixture
def settings() -> BustySettings:
    """BustySettings with fast timing for tests."""
    return BustySettings(
        discord_token="fake_token",
        dj_role_name="test_dj",
        testing_guild=None,
        data_dir=Path("data"),
        auth_dir=Path("auth"),
        state_dir=Path("data/state"),
        config_dir=Path("data/config"),
        cache_dir=Path("data/cache"),
        temp_dir=Path("data/temp"),
        attachment_cache_dir=Path("data/cache/attachments"),
        bot_state_file=Path("data/state/bot_state.json"),
        llm_context_file=Path("data/config/llm_context.json"),
        google_auth_file=Path("auth/service_account.json"),
        google_form_folder=None,
        openai_api_key=None,
        openai_model="gpt-4o",
        openai_tokenizer_model="gpt-4o",
        seconds_between_songs=0,  # No cooldown for tests
        num_longest_submitters=3,
        emoji_list=["🎵", "🎶", "🎸"],  # Sample emojis for tests
        mailbox_channel_prefix="bustys-mailbox-",  # Default for tests
        log_level=logging.INFO,  # Default log level for tests
    )


@pytest.fixture
def mock_output() -> MockBustOutput:
    """Fresh MockBustOutput instance."""
    return MockBustOutput()


@pytest.fixture
def mock_ai_service() -> MockAIService:
    """Fresh MockAIService instance."""
    return MockAIService()


@pytest.fixture
def mock_audio() -> MockAudioPlayer:
    """Fresh MockAudioPlayer instance (manual completion mode)."""
    return MockAudioPlayer(auto_complete=False)


@pytest.fixture
def mock_audio_auto() -> MockAudioPlayer:
    """MockAudioPlayer in auto-complete mode."""
    return MockAudioPlayer(auto_complete=True)


@pytest.fixture
def mock_user_preferences() -> MockUserPreferences:
    """Fresh MockUserPreferences instance."""
    return MockUserPreferences()


def make_track(
    filename: str,
    submitter_id: int = 123,
    submitter_name: str = "TestUser",
    duration: float | None = 180.0,
) -> Track:
    """Helper to create test Track instances."""
    return Track(
        local_filepath=Path(f"/fake/{filename}"),
        attachment_filename=filename,
        submitter_id=submitter_id,
        submitter_name=submitter_name,
        message_content=None,
        message_jump_url="https://discord.com/channels/1/2/3",
        attachment_url="https://cdn.discord.com/attachments/1/2/test.mp3",
        duration=duration,
    )


@pytest.fixture
def sample_tracks() -> list[Track]:
    """Sample track list for testing."""
    return [
        make_track(
            "track1.mp3", submitter_id=111, submitter_name="Alice", duration=180.0
        ),
        make_track(
            "track2.mp3", submitter_id=222, submitter_name="Bob", duration=200.0
        ),
        make_track(
            "track3.mp3", submitter_id=333, submitter_name="Charlie", duration=150.0
        ),
    ]
