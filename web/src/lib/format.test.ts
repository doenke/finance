import assert from 'node:assert/strict';
import { test } from 'node:test';
import { decimalToInput, formatDate, parseDecimal } from './format.ts';

test('parseDecimal understands German and plain input', () => {
  const cases: Record<string, string | null> = {
    '250.000': '250000',
    '2.345,67': '2345.67',
    '92,50': '92.50',
    '92.50': '92.50',
    '-89,90': '-89.90',
    '1.234.567,8': '1234567.8',
    '0.9999': '0.9999',
    '12 €': '12',
    '': '',
    abc: null
  };
  for (const [input, expected] of Object.entries(cases)) assert.equal(parseDecimal(input), expected, input);
});

test('decimalToInput and formatDate', () => {
  assert.equal(decimalToInput('1234.5000'), '1234,5');
  assert.equal(decimalToInput('100.00'), '100');
  assert.equal(formatDate('2026-11-23'), '23.11.2026');
});
