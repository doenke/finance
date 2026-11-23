// Global app state: configuration and the logged-in user.
import { api, ApiError, type AppConfig, type Me } from './api';

export const session = $state<{ config: AppConfig | null; me: Me | null; loading: boolean; error: string }>({
  config: null,
  me: null,
  loading: true,
  error: ''
});

export async function loadSession(): Promise<void> {
  session.loading = true;
  session.error = '';
  try {
    session.config = await api.get<AppConfig>('/api/config');
    try {
      session.me = await api.get<Me>('/api/me');
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) session.me = null;
      else throw e;
    }
  } catch (e) {
    session.error = e instanceof Error ? e.message : 'Server nicht erreichbar';
  } finally {
    session.loading = false;
  }
}

export async function logout(): Promise<void> {
  await api.post('/auth/logout');
  session.me = null;
}
