// Thin wrapper around fetch for the JSON API.

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string
  ) {
    super(message);
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method,
    headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
    credentials: 'same-origin'
  });
  if (!res.ok) {
    let message = `Fehler ${res.status}`;
    try {
      const data = await res.json();
      if (typeof data.detail === 'string') message = data.detail;
      else if (Array.isArray(data.detail)) message = 'Bitte prüfe die Eingaben.';
    } catch {
      // keep generic message
    }
    throw new ApiError(res.status, message);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  get: <T>(path: string) => request<T>('GET', path),
  post: <T>(path: string, body?: unknown) => request<T>('POST', path, body ?? {}),
  put: <T>(path: string, body: unknown) => request<T>('PUT', path, body),
  del: <T = void>(path: string) => request<T>('DELETE', path)
};

export interface AppConfig {
  version: string;
  provider_name: string;
  oidc_enabled: boolean;
  dev_login: boolean;
}

export interface Me {
  id: number;
  name: string;
  email: string;
  is_admin: boolean;
  avatar_url: string | null;
  person_id: number | null;
}

export interface Person {
  id: number;
  name: string;
  color: string;
  user_id: number | null;
  avatar_url: string | null;
  archived: boolean;
}
