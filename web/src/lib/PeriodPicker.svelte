<script lang="ts">
  let { value = $bindable('1Y'), periods = ['1M', 'YTD', '1Y', '3Y', '5Y', 'ALL'] }: { value?: string; periods?: string[] } = $props();
  const labels: Record<string, string> = { '1M': '1 M', YTD: 'YTD', '1Y': '1 J', '3Y': '3 J', '5Y': '5 J', ALL: 'Max' };
</script>

<div class="seg" role="radiogroup" aria-label="Zeitraum">
  {#each periods as p (p)}
    <button role="radio" aria-checked={value === p} class:active={value === p} onclick={() => (value = p)}>{labels[p] ?? p}</button>
  {/each}
</div>

<style>
  .seg {
    display: inline-flex;
    border: 1px solid var(--border);
    border-radius: 10px;
    overflow: hidden;
    max-width: 100%;
  }
  button {
    font: inherit;
    font-size: 0.85rem;
    border: 0;
    background: var(--surface);
    color: var(--text);
    padding: 6px 10px;
    cursor: pointer;
  }
  button + button {
    border-left: 1px solid var(--border);
  }
  button.active {
    background: var(--accent-soft);
    color: var(--accent-strong);
    font-weight: 600;
  }
</style>
