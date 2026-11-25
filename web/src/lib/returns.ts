// Return breakdown from /api/performance/breakdown, flattened so that depots and crypto accounts
// appear with their single positions instead of the account.
import { toNumber } from './format.ts';

export interface BreakdownPosition {
  instrument_id: number;
  name: string;
  gain: string;
  irr: string | null;
  ttwror: string | null;
  ttwror_pa: string | null;
  contribution: string | null;
  sold: boolean;
}
export interface BreakdownItem {
  positions: BreakdownPosition[] | null;
  account_id: number;
  name: string;
  kind_label: string;
  start_value: string;
  end_value: string;
  net_flows: string;
  gain: string;
  irr: string | null;
  ttwror: string | null;
  ttwror_pa: string | null;
  avg_capital: string;
  contribution: string | null;
  weight: string | null;
}
export interface Breakdown {
  from: string | null;
  to: string;
  total: { gain: string; avg_capital: string; simple_return: string | null; irr: string | null; ttwror: string | null; ttwror_pa: string | null } | null;
  items: BreakdownItem[];
}
export interface ReturnRow {
  key: string;
  name: string;
  sub: string;
  href: string;
  irr: string | null;
  ttwror: string | null;
  ttwror_pa: string | null;
  gain: string;
  contribution: string | null;
  /** fees and taxes of a depot that belong to no position */
  rest: boolean;
  /** no gain and no return in the period (e.g. a current account) */
  quiet: boolean;
}

const isQuiet = (gain: string, irr: string | null) => Math.abs(toNumber(gain)) < 0.5 && Math.abs(toNumber(irr ?? '0')) < 0.00005;

export function flattenBreakdown(items: BreakdownItem[]): ReturnRow[] {
  const out: ReturnRow[] = [];
  for (const i of items) {
    const href = `/konten/${i.account_id}`;
    if (!i.positions?.length) {
      out.push({ key: `a${i.account_id}`, name: i.name, sub: i.kind_label, href, irr: i.irr, ttwror: i.ttwror, ttwror_pa: i.ttwror_pa, gain: i.gain, contribution: i.contribution, rest: false, quiet: isQuiet(i.gain, i.irr) });
      continue;
    }
    let gain = toNumber(i.gain);
    let contribution = toNumber(i.contribution);
    for (const p of i.positions) {
      out.push({
        key: `p${i.account_id}-${p.instrument_id}`,
        name: p.name,
        sub: `${i.name}${p.sold ? ' · verkauft' : ''}`,
        href,
        irr: p.irr,
        ttwror: p.ttwror,
        ttwror_pa: p.ttwror_pa,
        gain: p.gain,
        contribution: p.contribution,
        rest: false,
        quiet: isQuiet(p.gain, p.irr)
      });
      gain -= toNumber(p.gain);
      contribution -= toNumber(p.contribution);
    }
    if (Math.abs(gain) >= 0.5)
      out.push({ key: `r${i.account_id}`, name: `${i.name}: Kosten & Steuern`, sub: 'ohne Position', href, irr: null, ttwror: null, ttwror_pa: null, gain: String(gain), contribution: String(contribution), rest: true, quiet: false });
  }
  return out;
}

/** Ranking by IRR (best first); positions without a return last. */
export function rankByIrr(rows: ReturnRow[]): ReturnRow[] {
  return rows
    .filter((r) => !r.rest && !r.quiet)
    .sort((a, b) => (a.irr === null ? 1 : 0) - (b.irr === null ? 1 : 0) || toNumber(b.irr) - toNumber(a.irr));
}
