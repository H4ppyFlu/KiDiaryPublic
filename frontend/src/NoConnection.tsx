/** What every screen shows when the API cannot be reached or cannot be understood. */
export default function NoConnection({ reason }: { reason: string }) {
  return (
    <section className="card card--bad">
      <h2>Keine Verbindung</h2>
      <p>{reason}</p>
    </section>
  )
}
