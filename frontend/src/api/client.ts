const BASE = ''  // same origin; Vite proxy handles /api in dev

class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

async function request<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const res = await fetch(BASE + path, {
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      ...(init.headers ?? {}),
    },
    ...init,
  })

  if (res.status === 401 || res.status === 403) {
    // Let the auth context handle redirect
    throw new ApiError(res.status, 'Unauthorized')
  }

  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      detail = body.detail ?? body.message ?? detail
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, detail)
  }

  // 204 No Content
  if (res.status === 204) return undefined as T

  const ct = res.headers.get('content-type') ?? ''
  if (ct.includes('application/json')) {
    return res.json() as Promise<T>
  }
  return res.text() as unknown as T
}

export const api = {
  get:    <T>(path: string)                 => request<T>(path, { method: 'GET' }),
  post:   <T>(path: string, body?: unknown) => request<T>(path, { method: 'POST',   body: body != null ? JSON.stringify(body) : undefined }),
  delete: <T>(path: string)                 => request<T>(path, { method: 'DELETE' }),
  patch:  <T>(path: string, body?: unknown) => request<T>(path, { method: 'PATCH',  body: body != null ? JSON.stringify(body) : undefined }),
}

export { ApiError }
