// IBAN helpers: check digits (ISO 13616, mod 97) and the German bank code inside the IBAN.

export function normalizeIban(input: string): string {
  return input.replace(/\s+/g, '').toUpperCase();
}

export function isValidIban(input: string): boolean {
  const iban = normalizeIban(input);
  if (!/^[A-Z]{2}\d{2}[A-Z0-9]{10,30}$/.test(iban)) return false;
  const rearranged = iban.slice(4) + iban.slice(0, 4);
  let rest = 0;
  for (const ch of rearranged) {
    const digits = /[A-Z]/.test(ch) ? String(ch.charCodeAt(0) - 55) : ch;
    for (const d of digits) rest = (rest * 10 + Number(d)) % 97;
  }
  return rest === 1;
}

/** Bank code (BLZ) of a German IBAN: characters 5–12. Returns null for other countries or invalid IBANs. */
export function blzFromIban(input: string): string | null {
  const iban = normalizeIban(input);
  if (!iban.startsWith('DE') || iban.length !== 22 || !isValidIban(iban)) return null;
  return iban.slice(4, 12);
}
