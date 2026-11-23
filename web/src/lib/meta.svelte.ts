// Static lists from the backend (account kinds, transaction types, ...), loaded once.
import { api } from './api.ts';

export interface KindMeta {
  key: string;
  label: string;
  mode: 'cash' | 'holdings' | 'valuation' | 'deposit' | 'loan';
  asset_class: string;
  liability: boolean;
}
export interface Option {
  key: string;
  label: string;
}
export interface Meta {
  kinds: KindMeta[];
  asset_classes: Option[];
  transaction_kinds: Option[];
  trade_types: Option[];
  instrument_kinds: Option[];
  units: Option[];
}

export const meta = $state<{ value: Meta | null }>({ value: null });
let loading: Promise<Meta> | null = null;

export function loadMeta(): Promise<Meta> {
  if (meta.value) return Promise.resolve(meta.value);
  loading ??= api.get<Meta>('/api/meta').then((m) => (meta.value = m));
  return loading;
}

export function label(list: Option[] | undefined, key: string): string {
  return list?.find((o) => o.key === key)?.label ?? key;
}
