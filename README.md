# musiclink

A WhatsApp bot that turns Spotify song links into Apple Music links.

Forward a Spotify link to the bot and it replies with the same song on Apple Music.

```
You:  https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT?si=...
Bot:  Never Gonna Give You Up – Rick Astley
      https://music.apple.com/us/album/never-gonna-give-you-up/1559885420?i=1559885421
```

## How it works

1. **Find the link** in the message and check it is really a Spotify track link.
2. **Read the song details** (title, artist, length) from the Spotify page's public preview tags.
3. **Search Apple Music** with the free iTunes Search API.
4. **Score each result** on title, artist and length, and mark down different versions (live, remix, instrumental).
5. **Reply** with one link if confident, up to three options if unsure, or "couldn't find it".

The conversion code (`src/musiclink/core`) knows nothing about WhatsApp, so other
front-ends can reuse it. The WhatsApp code is in `src/musiclink/whatsapp`.

## Try it without WhatsApp

Requires [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run musiclink 'https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT'
```

Add `--debug` to see match scores. Set `ITUNES_COUNTRY=sg` (or your country) in
front of the command to search a different Apple Music storefront.

## Run the WhatsApp bot

The bot uses Meta's official WhatsApp Cloud API with its free test number.

### 1. Create a Meta app

1. Go to <https://developers.facebook.com/apps> and create an app with the WhatsApp use case.
2. Open **WhatsApp > API Setup**. Note the **Phone number ID** and generate a temporary **access token**.
3. On the same page, add your own phone number to the list of allowed recipients and confirm the code WhatsApp sends you.
4. Open **App settings > Basic** and reveal the **App secret**.

### 2. Fill in `.env`

```bash
cp .env.example .env
```

Open `.env` and fill in each value. The file explains where each one comes from.

### 3. Start the bot and a tunnel

Meta needs a public HTTPS address to deliver messages to. During development a
tunnel forwards one to your machine.

```bash
uv run musiclink-bot
```

In a second terminal:

```bash
cloudflared tunnel --url http://localhost:8000
```

The tunnel prints an address like `https://something.trycloudflare.com`.

### 4. Register the webhook

1. In the Meta dashboard open the WhatsApp use case, then **Step 2. Production setup > Configure Webhooks**.
2. Set **Callback URL** to the tunnel address followed by `/webhook`.
3. Set **Verify token** to the `WHATSAPP_VERIFY_TOKEN` value from your `.env` (the value only, no quotes).
4. Click **Verify and save**, then subscribe to the **messages** webhook field.

The bot logs `Webhook verified by Meta` when this succeeds.

### 5. Publish the app

An unpublished app only receives test webhooks sent from the dashboard.

1. Under **App settings > Basic**, set **Privacy policy URL** to the tunnel address followed by `/privacy` and save.
2. Open **Publish** and publish the app.

No business phone number, payment method or business verification is needed for the test number.

### 6. Subscribe the app to the WhatsApp account

This step is easy to miss: the webhook can be verified and the `messages` field
ticked, and Meta will still deliver nothing until the app is subscribed to the
WhatsApp Business Account that owns the test number. The dashboard did not do
this automatically.

Check which apps are subscribed (the account ID is shown on the API Setup page):

```bash
curl -H "Authorization: Bearer $WHATSAPP_ACCESS_TOKEN" \
  "https://graph.facebook.com/v24.0/<WHATSAPP_BUSINESS_ACCOUNT_ID>/subscribed_apps"
```

If your app is not listed, subscribe it:

```bash
curl -X POST -H "Authorization: Bearer $WHATSAPP_ACCESS_TOKEN" \
  "https://graph.facebook.com/v24.0/<WHATSAPP_BUSINESS_ACCOUNT_ID>/subscribed_apps"
```

### 7. Use it

Send a Spotify song link to the test number from your own WhatsApp. The reply
arrives in the same chat a few seconds later.

### Troubleshooting

The bot logs to the terminal and to `musiclink.log`.

| Log line | Meaning |
|---|---|
| `Webhook verification failed` | The verify token in Meta does not match `.env` |
| Nothing when you send a message | Meta is not delivering: check steps 5 and 6, and that the tunnel address is current |
| `Ignored a message from a sender not on the list` | `ALLOWED_SENDERS` does not match your number |
| `Could not send the reply` | Meta refused the reply; the line says why (often an expired access token) |

Temporary access tokens expire after about a day; generate a new one and restart
the bot when replies stop arriving. The free tunnel address also changes each
time the tunnel restarts, so the Callback URL needs updating then.

## Host it on Render

Running on your own computer needs a tunnel whose address keeps changing.
Hosting gives the bot a fixed address and keeps it available when your
computer is off. The repo includes a `Dockerfile` and a `render.yaml` for
[Render](https://render.com)'s free tier.

1. **Get a permanent access token.** In Meta Business Settings, create a system
   user, give it your app and WhatsApp account, and generate a token that never
   expires with the `whatsapp_business_messaging` and
   `whatsapp_business_management` permissions.
2. **Push this repo to GitHub.**
3. **Create the service.** In Render choose **New > Blueprint**, pick the repo,
   and enter the five secret values when asked. They are stored by Render, not
   in the repo.
4. **Point Meta at it.** Once deployed, Render shows an address like
   `https://musiclink-xxxx.onrender.com`. In the Meta dashboard set the Callback
   URL to that address plus `/webhook` and the privacy policy URL to it plus
   `/privacy`.

The free tier puts the service to sleep after a period with no traffic. The
first message after that wakes it, so that reply takes longer; Meta re-sends a
webhook it got no answer to, and the bot ignores duplicates.

## Security

- **Secrets** are read from environment variables (`.env` is git-ignored) and are masked if printed.
- **Webhook signatures**: every incoming request must carry a valid `X-Hub-Signature-256` (HMAC-SHA256 with the app secret), compared in constant time.
- **Sender allowlist**: only phone numbers in `ALLOWED_SENDERS` get a response.
- **Strict link validation**: `https` only, exact host match, exact path pattern. The link is rebuilt from the track ID and never passed through as typed.
- **No blind redirects**: short links are expanded one hop at a time and each hop is re-validated, to prevent server-side request forgery.
- **Outgoing links are checked too**: Apple Music links are validated and rebuilt before being sent.
- **Limits**: request timeouts, capped response and body sizes, a per-sender rate limit, and duplicate-delivery detection.
- **Logs** contain no message text, tokens or full phone numbers. The HTTP access log is off because the verification request carries the verify token in its URL.

## Limitations

- Spotify's page tags are not an official API. If Spotify changes its pages the bot falls back to title-only matching and offers options instead of a single answer.
- Matching is by title, artist and length, not by a shared recording ID, so an unusual title can be missed.
- Traditional and Simplified Chinese spellings of the same title are not recognised as equal.
- Tracks only. Albums, playlists and Apple Music to Spotify are not supported.

## Development

```bash
uv run pytest             # tests (none of them use the network)
uv run ruff check .       # lint, including security rules
uv run ruff format .      # format
```
