---
status: proposed (confirm or reject in Phase 0)
---

# Read and send Messages through Beeper Desktop's local API, not as a Matrix client

The original design logged in to Beeper's Matrix homeserver with `matrix-nio`. Because uMessage runs on the same Mac as Beeper Desktop (ADR-0002), we instead talk to Beeper Desktop's local API on `127.0.0.1`, which lists Chats, reads Messages and sends them across every Platform Beeper supports. This avoids handling end-to-end encryption keys and device verification ourselves, and it sees Chats on Beeper's on-device bridges, which never reach the Matrix homeserver and would be invisible to a Matrix client.

## Considered Options

- **Matrix client (`matrix-nio`)**: standard protocol, works without Beeper Desktop open; but we own E2EE, and on-device-bridged Chats are invisible. Kept as the fallback if Phase 0 rejects this ADR.
- **Beeper Desktop local API** (proposed): Beeper handles Platforms and encryption; requires Beeper Desktop to be running, is less documented, and may need polling for new Messages.

## Consequences

- uMessage only ingests while Beeper Desktop is open; the UI must show when it is not.
- Beeper keeps the full history, so uMessage stores only a recent window of Messages (First Import takes about the last 50 per Chat active in the past 30 days, then every new Message) and asks Beeper for older history when the user scrolls back. Anchor Messages are never pruned.
- Phase 0 must confirm, for each of iMessage, Instagram, Messenger, WhatsApp and Discord: Chats are listed, a Message can be read, a Message can be sent; and find out whether new Messages are pushed or must be polled.
