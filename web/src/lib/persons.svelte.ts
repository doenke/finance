// Household members and the person filter ("Alle" or one person), remembered per device.
import { api, type Account, type Person } from './api.ts';
import { toNumber } from './format.ts';

const KEY = 'finanzen:person-filter';

function initialFilter(): number | null {
  try {
    const v = localStorage.getItem(KEY);
    return v ? Number(v) : null;
  } catch {
    return null;
  }
}

export const household = $state<{ persons: Person[]; filter: number | null }>({ persons: [], filter: initialFilter() });

export async function loadPersons(): Promise<Person[]> {
  household.persons = await api.get<Person[]>('/api/persons');
  if (household.filter !== null && !household.persons.some((p) => p.id === household.filter)) setFilter(null);
  return household.persons;
}

export function setFilter(id: number | null): void {
  household.filter = id;
  try {
    if (id === null) localStorage.removeItem(KEY);
    else localStorage.setItem(KEY, String(id));
  } catch {
    // ignore
  }
}

/** Share of the filtered person in an account (1 when no filter is active). */
export function shareOf(account: Account): number {
  if (household.filter === null) return 1;
  const owner = account.owners.find((o) => o.person_id === household.filter);
  return owner ? toNumber(owner.share) : 0;
}

export function personName(id: number): string {
  return household.persons.find((p) => p.id === id)?.name ?? '?';
}
