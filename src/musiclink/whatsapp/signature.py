"""Check that a webhook request really came from Meta.

Our webhook URL is public, so anyone on the internet can send requests to it.
Meta proves a request is genuine by signing it:

    signature = HMAC-SHA256(key = our app secret, message = the request body)

and sending the result in a header:

    X-Hub-Signature-256: sha256=3d5c...  (64 hex characters)

Only Meta and we know the app secret, so only Meta can produce a signature
that matches. We recompute it ourselves and compare.
"""

import hashlib
import hmac

PREFIX = "sha256="


def compute_signature(app_secret: str, body: bytes) -> str:
    """The header value Meta would send for this body."""
    digest = hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
    return PREFIX + digest


def is_valid_signature(app_secret: str, body: bytes, header: str | None) -> bool:
    """True only if `header` is the correct signature for `body`.

    `body` must be the raw bytes exactly as received. If we parsed the JSON
    and re-created it, spacing could change and the signature would not match.
    """
    if not header or not header.startswith(PREFIX):
        return False

    expected = compute_signature(app_secret, body)

    # compare_digest takes the same time whether the first or the last
    # character is wrong. A plain == stops at the first difference, and an
    # attacker could measure that tiny delay to guess the signature one
    # character at a time (a "timing attack").
    return hmac.compare_digest(expected.encode(), header.strip().lower().encode())
