# Kidiary

A private, shared diary about one child, kept by both parents. Each evening the app asks a short question and each parent answers as many as they feel like in one sitting; the answers accumulate into an archive of the child's growing up.

## Language

**Child**:
The person the diary is about. The archive exists for their sake, not the parents'.
_Avoid_: kid, baby

**Parent**:
One of the two people who receive prompts and write answers. There are exactly two, they are known to each other, and each sees everything the other writes.
_Avoid_: user, account, member

**Device**:
One phone or browser that has been given the PIN. A parent has as many as they carry, and each one says once which of the two parents is holding it — a claim the app takes at its word rather than a credential it checks (ADR-0010).
_Avoid_: client, installation, session (reserved for the authentication sense)

**Diary**:
The single shared archive of everything both parents have answered about the child. There is one, not one per parent.
_Avoid_: journal, log, feed

**Prompt**:
A question the app asks, e.g. "What was funny today?". Prompts live in a bank and are drawn repeatedly over time, independently for each parent, so a prompt is a reusable thing rather than a one-off.
_Avoid_: question, nudge

**Prompt bank**:
The full set of prompts the app can draw from. It is seeded once and edited by changing the seed, not from inside the app.
_Avoid_: question pool, prompt list

**Diary day**:
The day an answer belongs to, running 04:00 to 04:00 rather than midnight to midnight. An answer given at 01:30 belongs to the day that just ended, because parents of small children are awake at hours that do not respect calendars.
_Avoid_: date, calendar day

**Answer**:
What a parent writes in response to one prompt. An answer always belongs to exactly one parent — the diary is jointly readable, not jointly authored.
_Avoid_: response, reply, note

**Draw**:
Choosing the next prompt to put in front of a parent, and the prompt that comes out of it. Answering or skipping draws again, and the two parents are drawn for independently, so they are rarely looking at the same question.
_Avoid_: pick, selection, next question

**Sitting**:
One stretch of answering, from opening the app to ending it. A parent is shown one prompt at a time and may answer it, skip it, or end the sitting; answering or skipping draws the next prompt.
_Avoid_: session (reserved for the authentication sense), entry

**Skip**:
Declining the prompt in front of you and drawing the next one. A skip keeps the sitting going; it is not the same as ending the sitting.
_Avoid_: dismiss, ignore, pass

**Notification**:
The one push a parent gets in the evening, carrying a prompt so that they have thought of an answer before they open the app. One per parent per diary day, at a time each of them sets for themselves. The app is German and calls it _Erinnerung_ on screen, which is the one place the avoided word is the right one; in code, in English and in this glossary it is a notification.
_Avoid_: reminder, alert, message

**Delivery**:
The record that a parent's notification for one diary day has been claimed, and which prompt it carried. Written before the push is sent, so that a scheduler that restarts mid-evening sends nothing twice; it is also what lets a tap on the notification open the prompt it showed.
_Avoid_: send, dispatch, job
