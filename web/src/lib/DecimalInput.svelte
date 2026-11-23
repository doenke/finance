<script lang="ts">
  // Text input for amounts with German decimal comma; `value` is a plain decimal string ("1234.56").
  import { decimalToInput, parseDecimal } from './format.ts';

  let {
    value = $bindable(),
    placeholder = '',
    required = false,
    id = undefined,
    suffix = ''
  }: { value?: string | null; placeholder?: string; required?: boolean; id?: string; suffix?: string } = $props();

  let text = $state(decimalToInput(value));
  let invalid = $state(false);
  let lastValue = value;

  $effect(() => {
    // Update the text when the value is changed from outside.
    if (value !== lastValue) {
      text = decimalToInput(value);
      lastValue = value;
    }
  });

  function onInput() {
    const parsed = parseDecimal(text);
    invalid = parsed === null;
    if (parsed !== null) {
      value = parsed;
      lastValue = parsed;
    }
  }
</script>

<span class="wrap">
  <input {id} type="text" inputmode="decimal" autocomplete="off" bind:value={text} oninput={onInput} {placeholder} {required} aria-invalid={invalid} class:invalid />
  {#if suffix}<span class="suffix">{suffix}</span>{/if}
</span>

<style>
  .wrap {
    position: relative;
    display: block;
  }
  input {
    text-align: right;
    font-variant-numeric: tabular-nums;
  }
  .wrap:has(.suffix) input {
    padding-right: 32px;
  }
  .suffix {
    position: absolute;
    right: 12px;
    top: 50%;
    transform: translateY(-50%);
    color: var(--muted);
    pointer-events: none;
  }
  .invalid {
    border-color: var(--neg);
  }
</style>
