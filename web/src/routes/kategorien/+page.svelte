<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '#lib/api.ts';
  import { type CategoryOption } from '#lib/BookingTable.svelte';
  import BudgetTabs from '#lib/BudgetTabs.svelte';
  import { formatDate, formatMoney } from '#lib/format.ts';
  import Icon from '#lib/Icon.svelte';
  import Info from '#lib/Info.svelte';
  import Money from '#lib/Money.svelte';
  import RuleEditor, { type Rule } from '#lib/RuleEditor.svelte';

  interface Group {
    pattern: string;
    count: number;
    total: string;
    example: string;
    purpose: string;
    last: string;
  }
  interface SavedRule extends Rule {
    id: number;
    category: string | null;
    count: number;
    total: string;
  }

  let groups = $state<Group[]>([]);
  let rules = $state<SavedRule[]>([]);
  let categories = $state<CategoryOption[]>([]);
  let editing = $state<{ key: string; rule: Rule } | null>(null);
  let catEdit = $state<{ id: number | null; name: string; kind: string } | null>(null);
  let error = $state('');

  async function load() {
    try {
      const [cf, r, c] = await Promise.all([
        api.get<{ unknown_groups: Group[] }>('/api/cashflow?months=12'),
        api.get<SavedRule[]>('/api/category-rules'),
        api.get<CategoryOption[]>('/api/categories')
      ]);
      [groups, rules, categories] = [cf.unknown_groups, r, c];
    } catch (e) {
      error = (e as Error).message;
    }
  }
  onMount(load);

  async function afterSave() {
    editing = null;
    await load();
  }
  async function removeRule(r: SavedRule) {
    if (!confirm(`Regel „${r.pattern}“ → ${r.category} löschen?`)) return;
    await api.del(`/api/category-rules/${r.id}`);
    await load();
  }
  async function saveCategory(e: SubmitEvent) {
    e.preventDefault();
    if (!catEdit) return;
    try {
      const body = { name: catEdit.name, kind: catEdit.kind };
      if (catEdit.id === null) await api.post('/api/categories', body);
      else await api.put(`/api/categories/${catEdit.id}`, body);
      catEdit = null;
      await load();
    } catch (err) {
      error = (err as Error).message;
    }
  }
  async function removeCategory(c: CategoryOption) {
    if (!confirm(`Kategorie „${c.name}“ löschen? Buchungen und Verträge verlieren dann diese Kategorie.`)) return;
    await api.del(`/api/categories/${c.id}`);
    await load();
  }

  const newRule = (pattern: string): Rule => ({ pattern, field: 'any', direction: 'out', account_id: null, category_id: null });
  const expenseCategories = $derived(categories.filter((c) => c.kind !== 'income'));
  const fieldText: Record<string, string> = { any: '', counterparty: ' im Empfänger', purpose: ' im Zweck' };
  const KINDS: { key: string; label: string; hint: string }[] = [
    { key: 'expense', label: 'Ausgaben', hint: 'zählen als Ausgabe' },
    { key: 'income', label: 'Einnahmen', hint: 'zählen als Einnahme' },
    { key: 'transfer', label: 'Sparen & Anlegen', hint: 'zählen als gespart' },
    { key: 'internal', label: 'Umbuchungen', hint: 'zählen nicht' }
  ];
</script>

<svelte:head><title>Kategorien – Finanzen</title></svelte:head>

<div class="stack">
  <h1>Kategorien &amp; Regeln</h1>
  <BudgetTabs />
  {#if error}<p class="error">{error}</p>{/if}

  <section class="card stack">
    <h2>
      Häufig ohne Kategorie <span class="muted small">· letzte 12 Monate</span>
      <Info>Die häufigsten Ausgaben, die noch keiner Kategorie zugeordnet sind. Eine Regel gilt auch für alle künftigen Buchungen.</Info>
    </h2>
    {#if groups.length}
      <ul class="rows">
        {#each groups as g (g.pattern)}
          <li>
            <div class="grow">
              <strong class="ellipsis">{g.example}</strong>
              {#if g.purpose && g.purpose !== g.example}<span class="small ellipsis muted" title={g.purpose}>{g.purpose}</span>{/if}
              <span class="muted small">{g.count}× · zuletzt {formatDate(g.last)}</span>
            </div>
            <Money value={g.total} cents={false} />
            <button class="btn" onclick={() => (editing = { key: g.pattern, rule: newRule(g.pattern) })}>Regel anlegen</button>
          </li>
          {#if editing?.key === g.pattern}
            <li class="edit"><RuleEditor rule={editing.rule} categories={expenseCategories} onsaved={afterSave} oncancel={() => (editing = null)} /></li>
          {/if}
        {/each}
      </ul>
    {:else}
      <p class="muted small">Alle Ausgaben der letzten zwölf Monate haben eine Kategorie.</p>
    {/if}
  </section>

  <section class="card stack">
    <div class="row head">
      <h2>
        Regeln <span class="muted small">· {rules.length}</span>
        <Info>Die erste passende Regel gewinnt, längere (genauere) Muster zuerst. Kategorien aus „Verträge“ und einzeln zugewiesene Buchungen gehen immer vor; ohne Regel ordnet Finanzen bekannte Händler selbst zu.</Info>
      </h2>
      <button class="btn" onclick={() => (editing = { key: 'new', rule: newRule('') })}><Icon name="plus" size={18} /> Regel</button>
    </div>
    {#if editing?.key === 'new'}
      <RuleEditor rule={editing.rule} {categories} onsaved={afterSave} oncancel={() => (editing = null)} />
    {/if}
    <ul class="rows">
      {#each rules as r (r.id)}
        <li>
          <div class="grow">
            <span>enthält „<strong>{r.pattern}</strong>“{fieldText[r.field]}{r.direction === 'in' ? ' (Einnahmen)' : ''} → <strong>{r.category}</strong></span>
            <span class="muted small">{r.count} Buchungen · {formatMoney(r.total, 'EUR', false)}</span>
          </div>
          <button class="btn" onclick={() => (editing = { key: `r${r.id}`, rule: { ...r } })}>Ändern</button>
          <button class="btn icon danger" aria-label="Regel {r.pattern} löschen" title="Löschen" onclick={() => removeRule(r)}><Icon name="trash" size={18} /></button>
        </li>
        {#if editing?.key === `r${r.id}`}
          <li class="edit"><RuleEditor rule={editing.rule} {categories} onsaved={afterSave} oncancel={() => (editing = null)} /></li>
        {/if}
      {/each}
      {#if !rules.length}<li class="muted small">Noch keine eigenen Regeln.</li>{/if}
    </ul>
  </section>

  <section class="card stack">
    <div class="row head">
      <h2>Kategorien</h2>
      <button class="btn" onclick={() => (catEdit = { id: null, name: '', kind: 'expense' })}><Icon name="plus" size={18} /> Kategorie</button>
    </div>
    {#if catEdit}
      <form class="row catform" onsubmit={saveCategory}>
        <input bind:value={catEdit.name} placeholder="Name" required maxlength="80" aria-label="Name" />
        <select bind:value={catEdit.kind} aria-label="Art">
          {#each KINDS as k (k.key)}<option value={k.key}>{k.label}</option>{/each}
        </select>
        <button class="btn primary" type="submit">Speichern</button>
        <button class="btn" type="button" onclick={() => (catEdit = null)}>Abbrechen</button>
      </form>
    {/if}
    <div class="kinds">
      {#each KINDS as k (k.key)}
        <div>
          <h3>{k.label} <span class="muted small">· {k.hint}</span></h3>
          <ul class="rows">
            {#each categories.filter((c) => c.kind === k.key) as c (c.id)}
              <li>
                <span class="grow">{c.name}</span>
                <button class="btn icon" aria-label="{c.name} bearbeiten" title="Bearbeiten" onclick={() => (catEdit = { id: c.id, name: c.name, kind: c.kind })}><Icon name="edit" size={16} /></button>
                <button class="btn icon danger" aria-label="{c.name} löschen" title="Löschen" onclick={() => removeCategory(c)}><Icon name="trash" size={16} /></button>
              </li>
            {/each}
          </ul>
        </div>
      {/each}
    </div>
  </section>
</div>

<style>
  h1,
  h2,
  h3 {
    margin: 0;
  }
  h3 {
    font-size: 0.95rem;
    margin-bottom: 4px;
  }
  .head {
    justify-content: space-between;
    flex-wrap: wrap;
  }
  .small {
    font-size: 0.8rem;
  }
  .rows {
    list-style: none;
    margin: 0;
    padding: 0;
  }
  .rows li {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 6px 0;
    border-top: 1px solid var(--border);
    flex-wrap: wrap;
  }
  .rows li.edit {
    display: block;
    border-top: 0;
    padding-top: 0;
  }
  .grow {
    flex: 1;
    min-width: 0;
    display: grid;
  }
  .ellipsis {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .kinds {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(min(240px, 100%), 1fr));
    gap: 16px 24px;
  }
  .catform {
    flex-wrap: wrap;
    gap: 8px;
  }
  .catform input {
    flex: 1;
    min-width: 160px;
  }
</style>
