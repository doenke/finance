// Household members.
import { api, type Person } from './api.ts';

// The person filter was removed (shared household); forget a choice stored by older versions.
try {
  localStorage.removeItem('finanzen:person-filter');
} catch {
  // ignore
}

export const household = $state<{ persons: Person[] }>({ persons: [] });

export async function loadPersons(): Promise<Person[]> {
  household.persons = await api.get<Person[]>('/api/persons');
  return household.persons;
}

export function personName(id: number): string {
  return household.persons.find((p) => p.id === id)?.name ?? '?';
}
