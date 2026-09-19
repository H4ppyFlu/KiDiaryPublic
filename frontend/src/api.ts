/**
 * Every request the app makes to its own API, in one place.
 *
 * Two things were being spelled out at each call site and are said once here: the
 * German the UI falls back to when a request fails, and the fact that the API's two
 * refusals are screens rather than errors — a 401 is a device without the PIN, a 403
 * one that has not said which Parent is holding it (ADR-0010).
 */

/** The API answered, and said no. */
export class Refused extends Error {
  // Spelled out rather than a constructor property: `erasableSyntaxOnly` is on, so
  // TypeScript here may only ever be types being removed.
  readonly status: number

  constructor(status: number) {
    super(`Die API hat mit HTTP ${status} geantwortet.`)
    this.name = 'Refused'
    this.status = status
  }
}

/** Whether this refusal is one of the two the app has a screen for. */
export function sendsBackToASignInScreen(error: unknown): error is Refused {
  return error instanceof Refused && (error.status === 401 || error.status === 403)
}

export function reasonFor(error: unknown): string {
  return error instanceof Error ? error.message : 'Die App ist nicht erreichbar.'
}

export async function askApi<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(path, init)
  } catch {
    // The browser's own error text is English; the UI is German.
    throw new Error('Die App ist nicht erreichbar.')
  }
  if (!response.ok) {
    throw new Refused(response.status)
  }
  // 204 is how the API says "done" to the PIN and to the Parent choice.
  return response.status === 204 ? (undefined as T) : ((await response.json()) as T)
}

/**
 * A request that carries a body. DELETE is in here with the other two because a push
 * endpoint is a capability — anything holding it can push to that phone — and a URL
 * ends up in access logs, so it travels in the body like everything else.
 */
export function tellApi<T>(
  method: 'POST' | 'PUT' | 'DELETE',
  path: string,
  body: unknown,
): Promise<T> {
  return askApi<T>(path, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}
