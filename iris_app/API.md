# Iris web API

All bodies are JSON. Every message body is **sealed** (encrypted) by the sender;
the server stores and forwards it without reading it.

## The sealed format

The tool makes a random 64-byte key when it asks to be connected. Bytes 0-31 are
the AES-256 key, bytes 32-63 the HMAC-SHA256 key.

```
sealed = "v1." + base64url( iv[16] || AES-256-CBC(PKCS7(json)) || HMAC-SHA256(iv || ciphertext)[32] )
```

base64url without `=` padding. Receivers check the HMAC before decrypting.

## A tool's calls

Base: the address Iris is mounted at, for example `https://site/iris`.
After pairing, send `Authorization: Bearer <token>` on every call. A `401` means
the tool was disconnected (from the phone, or the token is wrong): forget the
token and offer to connect again.

| Call | Body / answer |
|---|---|
| `POST /api/tool/pair` | `{"name": "Sketch ProMax", "machine": "PC-01", "commands": ["Pause","Resume","Stop"]}` → `{"pair_id", "code", "secret", "expires_in"}` |
| `GET /api/tool/pair/<pair_id>` with header `X-Pair-Secret: <secret>` | `{"status": "waiting"}`, `{"status": "expired"}`, or once only `{"status": "connected", "tool_id", "token"}` |
| `GET /api/tool/me` | `{"id", "name", "machine"}`: a cheap "am I still connected?" |
| `POST /api/tool/messages` | `{"kind": "update" \| "question" \| "closed", "body": sealed, "reply_to"?: id}` → `{"id", "created"}` |
| `GET /api/tool/inbox?after=<id>` | `{"messages": [{"id", "side": "phone", "kind", "reply_to", "body", "created"}]}`: what the phone sent after `id` |
| `DELETE /api/tool/me` | Disconnect from the tool's side. |

Show the person this link as a QR code (and as text to copy):

```
<base>/pair?c=<code>#k=<base64url key>
```

Poll the pairing every 2-3 seconds while the QR window is open (codes last 10
minutes). Poll the inbox about every 30 seconds while a question waits, and every
few minutes otherwise.

## What goes inside a sealed body

| Kind | From | Value |
|---|---|---|
| `update` | tool | `{"text"}` |
| `question` | tool | `{"text", "options"?: [..], "assumed"?: "what happens with no answer", "deadline"?: ISO time}` |
| `closed` | tool | `{"text"}`, with `reply_to` = the question: settled on the PC (for example, went with the assumption). Late answers are refused. |
| `answer` | phone | `{"text"}`, with `reply_to` = the question |
| `command` | phone | `{"command"}`: one of the tool's `commands` |
| `message` | phone | `{"text"}`: free text to the tool |

Notifications: a question always notifies (unless the person turned the tool's
notifications off); updates notify only when they chose "Questions and updates".
