// Role of an account in the monthly balance (mirrors services/cashflow.role_of in the backend).
export type FlowRole = 'spending' | 'saving';

const DEFAULT_ROLE: Record<string, FlowRole> = { giro: 'spending', kreditkarte: 'spending', tagesgeld: 'saving', verrechnung: 'saving', festgeld: 'saving' };

/** Role a kind of account has without a choice; null for accounts without own bookings (pensions, loans …). */
export function defaultRole(kind: string, mode: string | undefined): FlowRole | null {
  if (kind in DEFAULT_ROLE) return DEFAULT_ROLE[kind];
  return mode === 'holdings' ? 'saving' : null;
}

export function flowRole(account: { kind: string; mode?: string; details?: Record<string, unknown> | null }): FlowRole | null {
  const chosen = account.details?.flow_role;
  if (chosen === 'spending' || chosen === 'saving') return chosen;
  return defaultRole(account.kind, account.mode);
}

export const ROLE_LABEL: Record<FlowRole, string> = { spending: 'Haushaltskonto', saving: 'Sparkonto' };
