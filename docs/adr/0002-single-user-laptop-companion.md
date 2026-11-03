# v1 is a single-user companion app that runs on the user's laptop

uMessage serves exactly one person: one Beeper account, one Google Calendar, no user accounts, with a static API token as the only authentication. It is a companion to the Beeper app rather than a replacement: reading and text replies only, with no media sending, reactions, read receipts, typing indicators or notifications, because event detection is the new value and rebuilding a full messenger adds nothing to it. It runs on the user's laptop, not an always-on server, so chats and keys stay on the user's own machine.

## Consequences

- The app is offline whenever the laptop sleeps, so catching up on Messages missed while asleep is a first-class concern, not an edge case.
- Supporting several users later would need a User model, per-user Matrix sessions and per-user Google tokens: a substantial rework.
