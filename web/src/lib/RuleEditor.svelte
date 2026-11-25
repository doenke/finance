<script lang="ts">
  // Create or edit a categorisation rule with a live preview of the bookings it hits.
  import { api } from './api.ts';
  import { formatDate, formatMoney } from './format.ts';
  import Money from './Money.svelte';

  export interface Rule {
    id?: number;
    pattern: string;
    field: 'any' | 'counterparty' | 'purpose';
    direction: 'any' | 'in' | 'out';
    account_id: number | null;
    category_id: number | null;
  }
  interface Preview {
    count: number;
    total: string;
    fixed: number;
    examples: { date: string; amount: string; counterparty: string; purpose: string; account: string | null; current: string | null; fixed: boolean }[];
  }

  let {
    rule,
    categories,
    accounts = [],
    onsaved,
    oncancel
  }: {
    rule: Rule;
    categories: { id: number; name: string; kind: string }[];
    accounts?: { id: number; name: string }[];
    onsaved: () => void;
    oncancel: () => void;
  } = $props();

  // a copy to edit; the parent passes a new rule for every editor it opens
  // svelte-ignore state_referenced_locally
  let form = $state<Rule>({ ...rule });
  let preview = $state<Preview | null>(null);
  let error = $state('');
  let timer: ReturnType<typeof setTimeout> | undefined;

  $effect(() => {
    const body = { pattern: form.pattern, field: form.field, direction: form.direction, account_id: form.account_id };
    clearTimeout(timer);
    if (body.pattern.trim().length < 2) {
      preview = null;
      return;
    }
    timer = setTimeout(async () => {
      try {
        preview = await api.post<Preview>('/api/category-rules/preview', body);
      } catch {
        preview = null;
      }
    }, 300);
  });

  async function addCategory() {
    const name = prompt('Name der neuen Kategorie');
    if (!name?.trim()) return;
    const c = await api.post<{ id: number; name: string; kind: string }>('/api/categories', { name: name.trim(), kind: form.direction === 'in' ? 'income' : 'expense' });
    categories = [...categories, c];
    form.category_id = c.id;
  }

  async function save(e: SubmitEvent) {
    e.preventDefault();
    error = '';
    try {
      if (form.id) await api.put(`/api/category-rules/${form.id}`, form);
      else await api.post('/api/category-rules', form);
      onsaved();
    } catch (err) {
      error = (err as Error).message;
    }
  }

  const fieldLabel = { any: 'Empfänger oder Verwendungszweck', counterparty: 'nur Empfänger', purpose: 'nur Verwendungszweck' };
</script>

<form class="editor stack" onsubmit={save}>
  <div class="grid">
    <label>Enthält <input bind:value={form.pattern} required minlength="2" maxlength="120" placeholder="z. B. rewe" /></label>
    <label>
      Suchen in
      <select bind:value={form.field}>
        {#each Object.entries(fieldLabel) as [k, v] (k)}<option value={k}>{v}</option>{/each}
      </select>
    </label>
    <label>
      Für
      <select bind:value={form.direction}>
        <option value="out">Ausgaben</option>
        <option value="in">Einnahmen</option>
        <option value="any">beides</option>
      </select>
    </label>
    <label>
      Konto
      <select bind:value={form.account_id}>
        <option value={null}>alle Konten</option>
        {#each accounts as a (a.id)}<option value={a.id}>{a.name}</option>{/each}
      </select>
    </label>
    <label>
      Kategorie
      <select bind:value={form.category_id} onchange={(e) => (e.currentTarget as HTMLSelectElement).value === 'new' && addCategory()} required>
        <option value={null} disabled>– wählen –</option>
        {#each categories as c (c.id)}<option value={c.id}>{c.name}</option>{/each}
        <option value="new">Neue Kategorie …</option>
      </select>
    </label>
  </div>
  {#if preview}
    <p class="small">
      Trifft <strong>{preview.count}</strong> Buchungen der letzten zwei Jahre ({formatMoney(preview.total)}).
      {#if preview.fixed}<span class="muted">{preview.fixed} davon haben ihre Kategorie aus „Verträge“ und bleiben so.</span>{/if}
    </p>
    {#if preview.examples.length}
      <div class="table-wrap">
        <table class="small">
          <tbody>
            {#each preview.examples as x, i (i)}
              <tr>
                <td>{formatDate(x.date)}</td>
                <td class="r"><Money value={x.amount} /></td>
                <td class="text">
                  <div class="ellipsis">{x.counterparty || '–'}</div>
                  <div class="ellipsis muted" title={x.purpose}>{x.purpose}</div>
                </td>
                <td class="muted">{x.current ? `bisher: ${x.current}` : 'bisher ohne'}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    {/if}
  {/if}
  {#if error}<p class="error small">{error}</p>{/if}
  <div class="row">
    <button class="btn primary" type="submit" disabled={!form.category_id || form.pattern.trim().length < 2}>Regel speichern</button>
    <button class="btn" type="button" onclick={oncancel}>Abbrechen</button>
  </div>
</form>

<style>
  .editor {
    padding: 12px;
    border: 1px solid var(--border);
    border-radius: 12px;
    background: var(--surface-2);
  }
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
    gap: 10px;
  }
  .small {
    font-size: 0.85rem;
    margin: 0;
  }
  .table-wrap {
    overflow-x: auto;
  }
  table {
    width: 100%;
    border-collapse: collapse;
  }
  td {
    padding: 3px 8px 3px 0;
    border-top: 1px solid var(--border);
    white-space: nowrap;
  }
  .r {
    text-align: right;
  }
  .text {
    white-space: normal;
    max-width: 420px;
  }
  .ellipsis {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  td.text .muted {
    font-size: 0.8rem;
  }
</style>
