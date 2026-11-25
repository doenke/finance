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
    onchanged
  }: { bookings: Booking[]; categories: CategoryOption[]; onchanged: () => Promise<void> | void } = $props();

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
          <td class="muted">{b.account}</td>
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
              {#if b.category_source && b.category_source !== 'fixed'}<div class="muted hint">{SOURCE_HINT[b.category_source] ?? ''}</div>{/if}
            {:else}
              <span class="muted" title="Zählt über die Kontenrollen, nicht über die Kategorie">Umbuchung zwischen Konten</span>
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
  .hint {
    font-size: 0.75rem;
  }
  .small {
    font-size: 0.85rem;
  }
</style>
