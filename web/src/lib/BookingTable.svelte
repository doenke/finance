<script lang="ts" module>
  export interface Booking {
    id: number;
    date: string;
    amount: string;
    counterparty: string;
    purpose: string;
    account: string;
    category_id: number | null;
    category_source: 'fixed' | 'rule' | 'keyword' | null;
    assignable: boolean;
    counts_as?: string;
    stale_category?: boolean;
    pattern?: string;
  }
  export interface CategoryOption {
    id: number;
    name: string;
    kind: string;
  }
</script>

<script lang="ts">
  // Single bookings with a category picker per row (assigning one booking wins over rules and keywords).
  import { api } from './api.ts';
  import { formatDate } from './format.ts';
  import Money from './Money.svelte';

  let {
    bookings,
    categories,
    onchanged,
    showCountsAs = false,
    onrule
  }: {
    bookings: Booking[];
    categories: CategoryOption[];
    onchanged: () => Promise<void> | void;
    showCountsAs?: boolean;
    onrule?: (b: Booking) => void;
  } = $props();

  const KIND_LABEL: Record<string, string> = { expense: 'Ausgaben', income: 'Einnahmen', transfer: 'Sparen & Anlegen', internal: 'Umbuchungen' };
  const SOURCE_HINT: Record<string, string> = { rule: 'per Regel', keyword: 'automatisch erkannt' };
  const groups = $derived(
    Object.entries(KIND_LABEL)
      .map(([kind, label]) => ({ label, items: categories.filter((c) => c.kind === kind) }))
      .filter((g) => g.items.length)
  );
  let saving = $state<number | null>(null);
  let error = $state('');

  async function assign(b: Booking, value: string) {
    saving = b.id;
    error = '';
    try {
      await api.put(`/api/transactions/${b.id}/category`, { category_id: value === '' ? null : Number(value) });
      await onchanged();
    } catch (e) {
      error = (e as Error).message;
    } finally {
      saving = null;
    }
  }
</script>

{#if error}<p class="error small">{error}</p>{/if}
<div class="table-wrap">
  <table class="small">
    <tbody>
      {#each bookings as b, i (`${b.id}-${i}`)}
        <tr>
          <td class="nowrap">{formatDate(b.date)}</td>
          <td class="r nowrap"><Money value={b.amount} /></td>
          <td>{b.counterparty || '–'}<div class="muted purpose">{b.purpose}</div></td>
          <td class="muted">{b.account}{#if showCountsAs && b.counts_as}<div class="counts">{b.counts_as}</div>{/if}</td>
          <td class="cat">
            {#if b.assignable}
              <select
                aria-label="Kategorie für {b.counterparty || b.purpose}"
                value={b.category_source === 'fixed' ? String(b.category_id) : ''}
                disabled={saving === b.id}
                onchange={(e) => assign(b, (e.currentTarget as HTMLSelectElement).value)}
              >
                <option value="">Automatisch{b.category_source && b.category_source !== 'fixed' ? ` (${categories.find((c) => c.id === b.category_id)?.name ?? '?'})` : ''}</option>
                {#each groups as g (g.label)}
                  <optgroup label={g.label}>
                    {#each g.items as c (c.id)}<option value={String(c.id)}>{c.name}</option>{/each}
                  </optgroup>
                {/each}
              </select>
              <div class="hint">
                {#if b.category_source && b.category_source !== 'fixed'}<span class="muted">{SOURCE_HINT[b.category_source] ?? ''}</span>{/if}
                {#if onrule}<button class="reset" onclick={() => onrule(b)}>Regel…</button>{/if}
              </div>
            {:else}
              <span class="muted" title="Zählt über die Kontenrollen, nicht über die Kategorie">Umbuchung zwischen Konten</span>
              {#if b.stale_category}
                <div>
                  <button class="reset" disabled={saving === b.id} onclick={() => assign(b, '')}>
                    Kategorie „{categories.find((c) => c.id === b.category_id)?.name ?? '?'}“ entfernen
                  </button>
                </div>
              {/if}
            {/if}
          </td>
        </tr>
      {/each}
    </tbody>
  </table>
</div>

<style>
  .table-wrap {
    overflow-x: auto;
  }
  table {
    width: 100%;
    border-collapse: collapse;
  }
  td {
    padding: 4px 8px 4px 0;
    border-top: 1px solid var(--border);
  }
  .r {
    text-align: right;
  }
  .nowrap {
    white-space: nowrap;
  }
  .purpose {
    font-size: 0.8rem;
    white-space: normal;
  }
  .cat select {
    max-width: 220px;
    font-size: 0.85rem;
  }
  .reset {
    background: none;
    border: 0;
    padding: 0;
    font: inherit;
    font-size: 0.8rem;
    color: var(--accent-strong);
    cursor: pointer;
    text-align: left;
  }
  .reset:hover {
    text-decoration: underline;
  }
  .counts {
    font-size: 0.75rem;
  }
  .hint {
    font-size: 0.75rem;
    display: flex;
    gap: 8px;
  }
  .hint .reset {
    font-size: 0.75rem;
  }
  .small {
    font-size: 0.85rem;
  }
</style>
