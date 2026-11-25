// German number and date formatting. Amounts travel as strings (Decimal) and are only formatted here.

const money = new Intl.NumberFormat('de-DE', { style: 'currency', currency: 'EUR' });
const moneyNoCents = new Intl.NumberFormat('de-DE', { style: 'currency', currency: 'EUR', maximumFractionDigits: 0 });
const pct = new Intl.NumberFormat('de-DE', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export function toNumber(value: string | number | null | undefined): number {
  if (value === null || value === undefined || value === '') return 0;
  return typeof value === 'number' ? value : Number(value);
}

export function formatMoney(value: string | number | null | undefined, currency = 'EUR', cents = true): string {
  if (value === null || value === undefined || value === '') return '–';
  const n = toNumber(value);
  if (currency !== 'EUR') {
    return new Intl.NumberFormat('de-DE', { style: 'currency', currency, maximumFractionDigits: cents ? 2 : 0 }).format(n);
  }
  return (cents ? money : moneyNoCents).format(n);
}

export function formatNumber(value: string | number | null | undefined, maxDigits = 4): string {
  if (value === null || value === undefined || value === '') return '–';
  return new Intl.NumberFormat('de-DE', { maximumFractionDigits: maxDigits }).format(toNumber(value));
}

export function formatPercent(value: string | number | null | undefined, signed = true): string {
  if (value === null || value === undefined || value === '') return '–';
  const n = toNumber(value);
  return `${signed && n > 0 ? '+' : ''}${pct.format(n)} %`;
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return '–';
  const [y, m, d] = value.split('-');
  return `${d}.${m}.${y}`;
}

/** ISO timestamp -> "25.11.2026, 14:05" in local time. */
export function formatDateTime(value: string | null | undefined): string {
  if (!value) return '–';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return '–';
  return d.toLocaleString('de-DE', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' });
}

export function today(): string {
  const d = new Date();
  const off = d.getTimezoneOffset();
  return new Date(d.getTime() - off * 60000).toISOString().slice(0, 10);
}

/** Parses user input like "1.234,56" or "1234.56" into "1234.56"; returns '' if empty and null if invalid. */
export function parseDecimal(input: string): string | null {
  let s = input.trim().replace(/\s|€|%/g, '');
  if (s === '') return '';
  if (s.includes(',')) s = s.replace(/\./g, '').replace(',', '.');
  // German thousands separators without decimals: "250.000" means 250000.
  else if (/^-?\d{1,3}(\.\d{3})+$/.test(s)) s = s.replace(/\./g, '');
  if (!/^-?\d*\.?\d*$/.test(s) || s === '-' || s === '.') return null;
  return s;
}

/** Formats a decimal string for an input field (German comma). */
export function decimalToInput(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === '') return '';
  let s = String(value);
  if (s.includes('.')) s = s.replace(/0+$/, '').replace(/\.$/, '');
  return s.replace('.', ',');
}
