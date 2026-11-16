"""Settings, read from environment variables (or a local .env file).

Secrets never live in the code. They live in .env on your machine, which git
ignores, and on a real server they would be set as environment variables.

If a required setting is missing the app refuses to start and says which one,
which is much better than failing later in the middle of a request.
"""

import re

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Read a file called .env if there is one. Names are not case-sensitive,
    # so the field `whatsapp_app_secret` is filled from WHATSAPP_APP_SECRET.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # SecretStr hides the value if a setting is ever printed or logged
    # (it shows as '**********'). Call .get_secret_value() to really use it.

    # A password you make up. Meta sends it back once, when you register the
    # webhook, to prove it is talking to your server.
    whatsapp_verify_token: SecretStr = Field(min_length=16)

    # The "App secret" from the Meta dashboard. Meta uses it to sign every
    # message it sends us; we use it to check those signatures.
    whatsapp_app_secret: SecretStr = Field(min_length=16)

    # Lets us send messages through the WhatsApp Cloud API.
    whatsapp_access_token: SecretStr = Field(min_length=16)

    # The ID of the bot's phone number (a long number; not the phone number itself).
    whatsapp_phone_number_id: str = Field(pattern=r"^\d{5,25}$")

    # Who may use the bot: phone numbers in international format, separated
    # by commas, e.g. "6591234567,60123456789". Everyone else is ignored.
    allowed_senders: str = Field(min_length=6)

    # Which Apple Music country to search, e.g. us, sg, my, gb.
    itunes_country: str = Field(default="us", pattern=r"^[A-Za-z]{2}$")

    # Version of Meta's Graph API. The Meta dashboard shows the current one.
    graph_api_version: str = Field(default="v24.0", pattern=r"^v\d{1,3}\.\d$")

    # --- Where and how the server runs (the defaults suit your own computer) ---

    # 127.0.0.1 = reachable from this computer only (right when a tunnel on
    # the same machine forwards to it). A hosting provider needs 0.0.0.0,
    # meaning "accept connections from outside", because its own front door
    # passes requests in from another machine.
    bind_host: str = Field(default="127.0.0.1", pattern=r"^(127\.0\.0\.1|0\.0\.0\.0)$")

    # Hosting providers such as Render tell the app which port to use
    # through the PORT environment variable.
    port: int = Field(default=8000, ge=1, le=65535)

    # Also write logs to this file. Leave empty to log to the terminal only,
    # which is what hosting providers expect (they collect terminal output).
    log_file: str = "musiclink.log"

    @field_validator("allowed_senders")
    @classmethod
    def _check_allowed_senders(cls, value: str) -> str:
        if not parse_phone_numbers(value):
            raise ValueError("must contain at least one phone number")
        return value

    @property
    def allowed_sender_set(self) -> frozenset[str]:
        return parse_phone_numbers(self.allowed_senders)


def parse_phone_numbers(text: str) -> frozenset[str]:
    """ "+65 9123 4567, 60123456789" -> {"6591234567", "60123456789"}.

    WhatsApp reports senders as digits only, so we store them the same way.
    """
    numbers = set()
    for piece in text.split(","):
        digits = re.sub(r"\D", "", piece)  # \D means "anything that is not a digit"
        if digits:
            numbers.add(digits)
    return frozenset(numbers)
