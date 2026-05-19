const DEFAULT_TIMEOUT_MS = 12_000

export class HttpError extends Error {
  status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = "HttpError"
    this.status = status
  }
}

export async function fetchWithTimeout(
  input: RequestInfo | URL,
  init: RequestInit = {},
  timeoutMs = DEFAULT_TIMEOUT_MS,
) {
  const controller = new AbortController()
  const timer = window.setTimeout(() => controller.abort(), timeoutMs)

  try {
    return await fetch(input, { ...init, signal: controller.signal })
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new Error("Request timed out. Check that the backend is running and try again.")
    }
    throw error
  } finally {
    window.clearTimeout(timer)
  }
}

export async function fetchJson<T>(
  input: RequestInfo | URL,
  init?: RequestInit,
  timeoutMs?: number,
): Promise<T> {
  const response = await fetchWithTimeout(input, init, timeoutMs)
  const text = await response.text()
  const data = text ? JSON.parse(text) : null

  if (!response.ok) {
    const message =
      data && typeof data === "object" && "detail" in data
        ? String(data.detail)
        : data && typeof data === "object" && "error" in data
          ? String(data.error)
          : text || `Request failed with status ${response.status}`
    throw new HttpError(message, response.status)
  }

  return data as T
}

export function errorMessage(error: unknown, fallback = "Something went wrong") {
  return error instanceof Error ? error.message : fallback
}
