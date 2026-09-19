# Which Parent is answering is a claim in the cookie, not a credential

The PIN is shared (ADR-0005), so the cookie it buys says only that a device holds the PIN. Every Answer, though, belongs to exactly one Parent. The two are joined in a second step: once a device is signed in it reads the two Parents, says which one it belongs to, and that choice is signed into the same cookie. Endpoints that write on a Parent's behalf require the Parent-bearing shape; the PIN exchange and the Parent list are reachable with the device-only one.

Nothing stops a device from claiming to be the other Parent. That is not a lock this app needs: both Parents already see everything either of them writes (ADR-0001), so there is nothing to be gained by it, and the locks that matter are the tailnet and the PIN.

## Considered Options

Letting the two Parents' names be read without the PIN was rejected. It would have folded "who are you?" into the PIN screen, but it reopens a rule that holds today — nothing but the PIN exchange answers a device without a cookie — for a screen each phone sees once a year.

Unlabelled "Elternteil 1 / Elternteil 2" buttons on the PIN screen would have avoided both the second step and the reading, and were rejected because they ask a person to remember a number for a name the app already knows.

Per-Parent PINs were never on the table; they are what ADR-0005 rules out.

## Consequences

The cookie has two valid shapes, and `GET /api/session` reports which one a device holds. That is what decides between the PIN screen, the "who are you?" screen and the Sitting.

A device belongs to one Parent. Two Parents sharing a phone would have to pick again, and there is deliberately no button for it: the phones are personal, and a wrong Answer is fixed in the database like a wrong Child is.
