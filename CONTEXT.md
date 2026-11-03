# uMessage

A personal companion to Beeper: one inbox across the user's messaging Platforms, which spots plans in conversations and, once the user approves, puts them on their Google Calendar.

## Language

### Conversations

**Platform**:
One of the messaging services a Chat lives on: iMessage, Instagram, Messenger, WhatsApp or Discord.
_Avoid_: Network, service, protocol, bridge

**Chat**:
One conversation, one-to-one or group, on exactly one Platform. Discord server channels are not Chats.
_Avoid_: Room, conversation, thread, channel

**Excluded Chat**:
A Chat the user has switched off plan detection for; it still appears in the inbox.
_Avoid_: Muted chat (muting is a notification setting in Beeper)

**First Import**:
The one-time load of existing Chats and recent Messages when uMessage first connects to Beeper; its Messages are never checked for plans.
_Avoid_: Backfill, initial sync

**Message**:
A single text sent in a Chat, by the user or by someone else.
_Avoid_: Post, event

**Outbound Message**:
A Message the user sent, whether from uMessage or from another client.
_Avoid_: Reply (a reply is just the act of sending one)

**Matrix event**:
The protocol object that Messages arrive as; the term exists only at the boundary with Beeper and is never shortened to "event".
_Avoid_: Event (bare)

### Plans and the calendar

**Detected Event**:
A plan the user would attend at a specific date and time (a dinner, an appointment, a meeting), found in a Chat and awaiting or past the user's review. Deadlines, other people's happenings, and vague intentions without an agreed time are not Detected Events.
_Avoid_: Event (bare), suggestion, candidate

**Anchor Message**:
The latest Message that shaped a Detected Event; the inbox shows the Detected Event beneath it, and links back to the plan jump to it.
_Avoid_: Source message, trigger message

**Pending Review**:
The state of a Detected Event the user has not yet confirmed or dismissed.

**Confirmed**:
The state of a Detected Event the user approved, which now has a Calendar Entry.

**Dismissed**:
The state of a Detected Event the user rejected; it never reaches the calendar.
_Avoid_: Deleted, ignored

**Calendar Entry**:
The item on the user's Google Calendar created when a Detected Event is Confirmed.
_Avoid_: Calendar event, gcal event, event (bare)
