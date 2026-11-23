<script lang="ts">
  // Horizontal bars for a share of a total (labels name the categories; one hue = magnitude).
  let {
    items,
    format,
    total = null,
    money = false
  }: { items: { key: string; label: string; value: number; color?: string }[]; format: (v: number) => string; total?: number | null; money?: boolean } = $props();
  const max = $derived(Math.max(...items.map((i) => Math.abs(i.value)), 1));
  const sum = $derived(total ?? items.reduce((s, i) => s + Math.max(i.value, 0), 0));
  let hover = $state<string | null>(null);
</script>

<ul class="bars">
  {#each items as item (item.key)}
    <li onpointerenter={() => (hover = item.key)} onpointerleave={() => (hover = null)} class:active={hover === item.key}>
      <div class="row">
        <span class="label">{item.label}</span>
        <span class="value"><span class:money>{format(item.value)}</span>{#if sum > 0 && item.value > 0}<span class="pct"> · {Math.round((item.value / sum) * 100)} %</span>{/if}</span>
      </div>
      <div class="track">
        <div class="bar" style:width="{(Math.abs(item.value) / max) * 100}%" style:background={item.color ?? 'var(--bar)'}></div>
      </div>
    </li>
  {/each}
</ul>

<style>
  .bars {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: 10px;
  }
  .row {
    display: flex;
    justify-content: space-between;
    gap: 12px;
    font-size: 0.9rem;
    margin-bottom: 4px;
  }
  .label {
    color: var(--text);
  }
  .value {
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
  }
  .pct {
    color: var(--muted);
  }
  .track {
    height: 8px;
    border-radius: 4px;
    background: var(--surface-2);
  }
  .bar {
    height: 100%;
    border-radius: 4px;
    min-width: 2px;
  }
  li.active .bar {
    filter: brightness(1.1);
  }
</style>
