<script lang="ts">
  import { formatMoney, toNumber } from './format.ts';
  let { value, currency = 'EUR', colored = false, cents = true }: { value: string | number | null; currency?: string; colored?: boolean; cents?: boolean } =
    $props();
  const n = $derived(toNumber(value));
</script>

<span class="num money" class:pos={colored && n > 0} class:neg={colored && n < 0}>{formatMoney(value, currency, cents)}</span>

<style>
  .pos {
    color: var(--pos);
  }
  .neg {
    color: var(--neg);
  }
</style>
