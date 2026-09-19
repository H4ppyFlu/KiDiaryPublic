import NoConnection from './NoConnection.tsx'
import NotificationTime from './NotificationTime.tsx'
import type { Refused } from './api.ts'
import type { NotificationSwitch } from './push.ts'

type Props = NotificationSwitch & {
  /** Whether to offer a way onwards from here, which is what this screen being the
   *  first thing a new device sees calls for, and a Parent who came here on purpose
   *  does not. */
  offerAWayOnwards: boolean
  onDone: () => void
  onRefused: (refusal: Refused) => void
}

/**
 * "Soll dich das Handy abends erinnern?" — asked once per device, right after it has
 * said who is holding it, and reachable from the nav for ever after.
 *
 * This screen is the whole reason the permission prompt is survivable. The browser's
 * dialog says nothing a Parent can judge, so the explanation has to be here, before
 * the tap; and on iOS a dismissed dialog is the end of the feature until the app is
 * deleted and installed again. Everything below is therefore written to be read once,
 * in an evening, by somebody who is tired.
 *
 * Under the switch, and only once this device has been past the question, sits the hour
 * the notification arrives at. It is deliberately second: a phone being set up has one
 * decision to make and it is not what time it is, and a Parent who has not said yes yet
 * would be reading about the timing of something they have not agreed to.
 */
export default function Notifications(props: Props) {
  const { state, offerAWayOnwards, onRefused } = props

  // Not while the switch is still working out which position it is in, and never where
  // this stack could not send anything anyway: an hour set for a notification that has
  // nowhere to come from is a setting that lies. A switch that merely *failed* to ask
  // still gets the hour — that is a hiccup on the way to `/api/push/key`, and a Parent
  // must not lose a working setting to it.
  const worthSetting = state.status !== 'checking' && state.status !== 'unconfigured'

  return (
    <>
      <TheSwitch {...props} />
      {worthSetting && !offerAWayOnwards && <NotificationTime onRefused={onRefused} />}
    </>
  )
}

/**
 * Which of the eight things this device is, said in the one sentence that fits it.
 *
 * Split out from the component above only so that the hour below it is written once
 * rather than eight times; each branch is still a whole screen on its own. A component
 * rather than a function called in the middle of one, so that a branch which one day
 * needs a hook of its own can simply have one.
 */
function TheSwitch({ state, busy, turnOn, turnOff, offerAWayOnwards, onDone }: Props) {
  if (state.status === 'checking') {
    return <p className="checking">Einen Moment …</p>
  }

  if (state.status === 'failed') {
    return <NoConnection reason={state.reason} />
  }

  const carryOn = offerAWayOnwards && (
    <div className="choices">
      <button type="button" onClick={onDone}>
        Weiter zur ersten Frage
      </button>
    </div>
  )

  if (state.status === 'on') {
    return (
      <section className="card card--good">
        <h2>Erinnerung ist an</h2>
        <p>
          Dieses Gerät bekommt abends eine Frage aufs Handy. Deine anderen Geräte musst du einzeln
          einschalten — und was du hier änderst, ändert für deinen Partner nichts.
        </p>
        <div className="choices">
          <button type="button" className="quiet" disabled={busy} onClick={turnOff}>
            Auf diesem Gerät ausschalten
          </button>
        </div>
        {carryOn}
      </section>
    )
  }

  if (state.status === 'off') {
    return (
      <section className="card">
        <h2>Soll dich das Handy abends erinnern?</h2>
        <p>
          Einmal am Abend eine kurze Frage — „Was war heute neu?“ — und du hast die Antwort schon
          im Kopf, bevor du die App öffnest. Ohne Erinnerung funktioniert alles hier genauso, nur
          musst du selbst daran denken.
        </p>
        <p>
          Beim Einschalten fragt gleich noch dein Browser nach. Das ist die Frage, auf die es
          ankommt: sag dort ja.
        </p>
        {state.dismissed && (
          <p className="aside">
            Die Nachfrage des Browsers wurde weggetippt, ohne sie zu beantworten. Das ist nicht
            schlimm — tipp einfach noch einmal.
          </p>
        )}
        <div className="choices">
          <button type="button" disabled={busy} onClick={turnOn}>
            Erinnerung einschalten
          </button>
          {offerAWayOnwards && (
            <button type="button" className="quiet" onClick={onDone}>
              Später
            </button>
          )}
        </div>
      </section>
    )
  }

  if (state.status === 'blocked') {
    return (
      <section className="card card--bad">
        <h2>Der Browser lässt keine Mitteilungen zu</h2>
        <p>
          Auf diesem Gerät wurden Mitteilungen abgelehnt. Die App darf nicht noch einmal fragen —
          das geht nur in den Einstellungen des Geräts:
        </p>
        <ul>
          <li>
            <strong>iPhone:</strong> Einstellungen → Mitteilungen → Kidiary → „Mitteilungen
            erlauben“. Steht Kidiary dort nicht, hilft nur: die App vom Home-Bildschirm löschen und
            noch einmal hinzufügen.
          </li>
          <li>
            <strong>Android:</strong> im Browser das Schloss-Symbol neben der Adresse antippen →
            „Berechtigungen“ → Mitteilungen erlauben.
          </li>
        </ul>
        {carryOn}
      </section>
    )
  }

  if (state.status === 'unsupported') {
    return (
      <section className="card">
        <h2>Hier gehen keine Mitteilungen</h2>
        <p>
          Dieses Fenster kann keine Mitteilungen empfangen. Auf dem iPhone heißt das fast immer:
          Kidiary läuft gerade als Tab in Safari statt als App. Über „Teilen“ → „Zum Home-Bildschirm“
          hinzufügen, die App von dort öffnen und hier wieder vorbeischauen.
        </p>
        {carryOn}
      </section>
    )
  }

  if (state.status === 'no-worker') {
    return (
      <section className="card">
        <h2>Noch nicht bereit</h2>
        <p>
          Der Service Worker läuft auf diesem Gerät nicht — ohne ihn kommt keine Mitteilung an.
          Beim Entwickeln ist das normal: er wird erst gebaut. Auf dem Handy hilft meistens, die
          App einmal zu schließen und neu zu öffnen.
        </p>
        {carryOn}
      </section>
    )
  }

  if (state.status === 'unconfigured') {
    return (
      <section className="card">
        <h2>Auf diesem Server nicht eingerichtet</h2>
        <p>
          Kidiary hat hier keine VAPID-Schlüssel, und ohne die kann niemand Mitteilungen
          verschicken. Das ist nichts, was sich am Handy beheben lässt: die beiden Schlüssel
          gehören in die <code>.env</code> neben dem Stack (siehe <code>README.md</code>).
        </p>
        {carryOn}
      </section>
    )
  }

  // Eight states, eight screens. `never` is the compiler keeping that true: a state
  // added to `NotificationState` without a sentence to go with it fails the build.
  const everyStateHasAScreen: never = state
  return everyStateHasAScreen
}
