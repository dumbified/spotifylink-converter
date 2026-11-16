# whatsapp spotifylink-converter

A WhatsApp bot that turns Spotify song links into Apple Music links.

```
You:  https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT?si=...
Bot:  Never Gonna Give You Up – Rick Astley
      https://music.apple.com/us/album/never-gonna-give-you-up/1559885420?i=1559885421
```

## How it works

1. Find the Spotify track link in the message and validate it.
2. Read the title, artist and length from the Spotify page's public preview tags.
3. Search Apple Music with the free iTunes Search API.
4. Score each result on title, artist and length; mark down other versions (live, remix, instrumental).
5. Reply with one link if confident, up to three options if unsure, or "couldn't find it".

The conversion code (`src/musiclink/core`) knows nothing about WhatsApp, so other
front-ends can reuse it. The WhatsApp code is in `src/musiclink/whatsapp`.

## Try it without WhatsApp

Requires [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run musiclink 'https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT'
```

Add `--debug` to see match scores. Prefix with `ITUNES_COUNTRY=sg` (or your country) to search another storefront.

## Run the WhatsApp bot

Uses Meta's official WhatsApp Cloud API and its free test number.

1. **Create a Meta app** at <https://developers.facebook.com/apps> with the WhatsApp use case. From **API Setup** note the phone number ID, generate an access token, and add your own number as a recipient. From **App settings > Basic** copy the app secret.
2. **Fill in the settings:** `cp .env.example .env`, then follow the comments in the file.
3. **Start the bot and a tunnel** (Meta needs a public HTTPS address):
   ```bash
    uv run musiclink-bot
    cloudflared tunnel --url http://localhost:8000   # in a second terminal
   ```
4. **Register the webhook** under **Configure Webhooks**: Callback URL = tunnel address + `/webhook`, Verify token = `WHATSAPP_VERIFY_TOKEN` from `.env` (value only, no quotes). Save, then subscribe to the **messages** field.
5. **Publish the app.** Set the privacy policy URL to tunnel address + `/privacy`, then publish. An unpublished app only receives dashboard test webhooks. No business number, payment or verification is needed.
6. **Subscribe the app to the WhatsApp Business Account.** Without this, Meta delivers nothing even with the webhook verified, and the dashboard may not do it for you:
   ```bash
    curl -X POST -H "Authorization: Bearer $WHATSAPP_ACCESS_TOKEN" \
      "https://graph.facebook.com/v24.0/<WHATSAPP_BUSINESS_ACCOUNT_ID>/subscribed_apps"
   ```
7. **Send a Spotify link** to the test number. The reply arrives in the same chat.

Temporary access tokens last about a day, and the tunnel address changes on every restart.

### Troubleshooting

Logs go to the terminal and `musiclink.log`.

| Log line | Meaning |
|---|---|
| `Webhook verification failed` | Verify token in Meta does not match `.env` |
| Nothing when you send a message | Meta is not delivering: check steps 5 and 6 and the tunnel address |
| `Ignored a message from a sender not on the list` | `ALLOWED_SENDERS` does not match your number |
| `Could not send the reply` | Meta refused the reply; the line says why (often an expired token) |

## Host it on Render

A `Dockerfile` and `render.yaml` are included for [Render](https://render.com)'s free tier, which gives a fixed address.

1. Create a permanent access token: a system user in Meta Business Settings with the `whatsapp_business_messaging` and `whatsapp_business_management` permissions.
2. Push the repo to GitHub and create a Render Blueprint (or a Docker web service) from it. Enter the five secrets in Render's dashboard.
3. In Meta, set the Callback URL to the Render address + `/webhook` and the privacy policy URL to it + `/privacy`.

The free tier sleeps when idle, so the first reply after a quiet period is slower. Meta re-sends unanswered webhooks and the bot ignores duplicates.

## Security

- **Secrets** come from environment variables (`.env` is git-ignored) and are masked if printed.
- **Webhook signatures:** every request must carry a valid `X-Hub-Signature-256` (HMAC-SHA256), compared in constant time.
- **Sender allowlist:** only numbers in `ALLOWED_SENDERS` get a response.
- **Strict link validation:** `https`, exact host, exact path. Links are rebuilt from the track ID, never passed through.
- **No blind redirects:** short links are expanded one hop at a time and re-validated, to prevent SSRF.
- **Outgoing links** from Apple are validated and rebuilt before sending.
- **Limits:** timeouts, size caps, per-sender rate limit, duplicate detection.
- **Logs** hold no message text, tokens or full phone numbers. The HTTP access log is off because Meta's verification request carries the verify token in its URL.

## Limitations

- Spotify's page tags are not an official API. If they change, the bot falls back to title-only matching and offers options.
- Matching uses title, artist and length, not a shared recording ID, so unusual titles can be missed.
- Traditional and Simplified Chinese spellings of a title are not treated as equal.
- Tracks only: no albums, playlists, or Apple Music to Spotify.

## Development

```bash
uv run pytest         # tests (no network needed)
uv run ruff check .   # lint, including security rules
uv run ruff format .  # format
```
