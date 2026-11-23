<script lang="ts">
  import { household, setFilter } from './persons.svelte.ts';
  const active = $derived(household.persons.filter((p) => !p.archived));
</script>

{#if active.length > 1}
  <div class="chips" role="radiogroup" aria-label="Person">
    <button role="radio" aria-checked={household.filter === null} class:active={household.filter === null} onclick={() => setFilter(null)}>Alle</button>
    {#each active as p (p.id)}
      <button role="radio" aria-checked={household.filter === p.id} class:active={household.filter === p.id} onclick={() => setFilter(p.id)}>
        <span class="dot" style:background={p.color}></span>{p.name}
      </button>
    {/each}
  </div>
{/if}

<style>
  .chips {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
  }
  button {
    font: inherit;
    font-size: 0.9rem;
    display: inline-flex;
    align-items: center;
    gap: 6px;
    border: 1px solid var(--border);
    background: var(--surface);
    color: var(--text);
    border-radius: 999px;
    padding: 4px 12px;
    cursor: pointer;
  }
  button.active {
    background: var(--accent-soft);
    border-color: var(--accent);
    color: var(--accent-strong);
    font-weight: 600;
  }
  .dot {
    width: 10px;
    height: 10px;
    border-radius: 50%;
  }
</style>
