// Remembered benchmark choice (per device).
const KEY = 'finanzen:benchmark';

function initial(): number | null {
  try {
    const v = localStorage.getItem(KEY);
    return v ? Number(v) : null;
  } catch {
    return null;
  }
}

export const benchmarkChoice = $state<{ id: number | null }>({ id: initial() });

export function setBenchmark(id: number | null): void {
  benchmarkChoice.id = id;
  try {
    if (id === null) localStorage.removeItem(KEY);
    else localStorage.setItem(KEY, String(id));
  } catch {
    // ignore
  }
}
