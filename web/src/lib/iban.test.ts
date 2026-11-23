import assert from 'node:assert/strict';
import { test } from 'node:test';
import { blzFromIban, isValidIban } from './iban.ts';

test('blzFromIban reads the bank code of German IBANs', () => {
  assert.equal(blzFromIban('DE89 3704 0044 0532 0130 00'), '37040044');
  assert.equal(blzFromIban('de89370400440532013000'), '37040044');
  assert.equal(blzFromIban('DE88 3704 0044 0532 0130 00'), null); // wrong check digits
  assert.equal(blzFromIban('AT61 1904 3002 3457 3201'), null); // not German
  assert.equal(blzFromIban('DE89 3704'), null);
});

test('isValidIban', () => {
  assert.ok(isValidIban('GB82 WEST 1234 5698 7654 32'));
  assert.ok(!isValidIban('GB82 WEST 1234 5698 7654 33'));
});
