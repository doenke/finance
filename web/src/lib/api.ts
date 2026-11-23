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

export interface Owner {
  person_id: number;
  share: string;
}

export interface Account {
  id: number;
  name: string;
  kind: string;
  kind_label: string;
  mode: 'cash' | 'holdings' | 'valuation' | 'deposit' | 'loan';
  asset_class: string;
  liability: boolean;
  institution: string;
  iban: string;
  currency: string;
  opened_on: string | null;
  closed: boolean;
  notes: string;
  details: Record<string, any>;
  settlement_account_id: number | null;
  owners: Owner[];
  value: string;
  value_as_of: string | null;
  missing_prices: number;
}

export interface Balance {
  id: number;
  date: string;
  amount: string;
  source: string;
}

export interface Transaction {
  id: number;
  account_id: number;
  booking_date: string;
  value_date: string | null;
  amount: string;
  kind: string;
  counterparty: string;
  purpose: string;
  transfer_account_id: number | null;
}

export interface Valuation {
  id: number;
  date: string;
  value: string;
  note: string;
}

export interface Instrument {
  id: number;
  kind: string;
  name: string;
  isin: string | null;
  wkn: string | null;
  symbol: string | null;
  currency: string;
  unit: string;
  price_source: string;
  price_symbol: string | null;
  details: Record<string, any>;
  last_price: string | null;
  last_price_date: string | null;
}

export interface Trade {
  id: number;
  date: string;
  type: string;
  instrument_id: number | null;
  quantity: string;
  price: string | null;
  amount: string;
  fees: string;
  taxes: string;
  note: string;
}

export interface Position {
  instrument: Instrument;
  quantity: string;
  cost: string;
  price: string | null;
  price_date: string | null;
  value: string;
  gain: string;
  gain_pct: string | null;
  realized: string;
  income: string;
  stale: boolean;
}

export interface PriceRow {
  id: number;
  date: string;
  close: string;
  source: string;
}

export interface ScheduleRow {
  date: string;
  payment: string;
  interest: string;
  principal: string;
  prepayment: string;
  balance: string;
  planned: boolean;
}

export interface Schedule {
  rows: ScheduleRow[];
  start_balance: string;
  start_date: string | null;
  balance_today: string;
  balance_at_fixed_until: string | null;
  end_date: string | null;
  interest_paid: string;
  interest_remaining: string;
  prepaid_this_year: string;
  prepayment_allowance: string | null;
}

export interface ReturnSummary {
  start_value: string;
  end_value: string;
  net_flows: string;
  gain: string;
  ttwror: string | null;
  ttwror_pa: string | null;
  irr: string | null;
  days: number;
}

export interface PerformanceData {
  from: string | null;
  to: string;
  inception?: string;
  summary: ReturnSummary | null;
  periods: Record<string, ReturnSummary>;
  series: { date: string; value: string; invested: string; ttwror: string }[];
}

export interface NetWorthData {
  series: { date: string; assets: string; liabilities: string; net: string; by_class: Record<string, string> }[];
  current: {
    assets: string;
    liabilities: string;
    net: string;
    by_class: Record<string, string>;
    change_month: string | null;
    change_ytd: string | null;
  } | null;
}
