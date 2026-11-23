<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '#lib/api.ts';
  import BarList from '#lib/charts/BarList.svelte';
  import { formatDate, formatMoney, toNumber } from '#lib/format.ts';
  import Money from '#lib/Money.svelte';

  interface Info {
    amount: string;
    amount_varies: boolean;
    monthly: string;
    yearly: string;
    count: number;
    first_date: string | null;
    last_date: string | null;
    last_amount: string | null;
    next_date: string | null;
    overdue: boolean;
    changed: { from: string; to: string; date: string } | null;
    account: string | null;
    direction: 'in' | 'out';
    interval: string;
    interval_label: string;
  }
  interface Item extends Info {
    id: number;
    name: string;
    status: 'active' | 'ended';
    note: string;
    category_id: number | null;
    category: string | null;
    category_kind: 'expense' | 'income' | 'transfer';
  }
  interface Suggestion extends Info {
    match_key: string;
    amount_min: string | null;
    amount_max: string | null;
    name: string;
    category_id: number | null;
    example: string;
  }
  interface Category {
    id: number;
    name: string;
    kind: 'expense' | 'income' | 'transfer';
  }
  interface Overview {
    summary: { income: string; costs: string; savings: string; free: string };
    by_category: { name: string; monthly: string }[];
    items: Item[];
    suggestions: Suggestion[];
    upcoming: { id: number; name: string; date: string; amount: string; direction: 'in' | 'out'; overdue: boolean }[];
    categories: Category[];
    intervals: { key: string; label: string }[];
    has_transactions: boolean;
  }
  interface Tx {
    id: number;
    date: string;
    amount: string;
    purpose: string;
    account: string | null;
  }

  let data = $state<Overview | null>(null);
  let error = $state('');
  let open = $state<number | null>(null);
  let edit = $state<{ name: string; interval: string; category_id: number | null; status: string; note: string } | null>(null);
  let txs = $state<Tx[]>([]);
  let showEnded = $state(false);
  let busy = $state(false);

  async function load() {
    try {
      data = await api.get<Overview>('/api/recurring');
    } catch (e) {
      error = (e as Error).message;
    }
  }
  onMount(load);

  const eur = (v: number) => formatMoney(v, 'EUR', false);
  const amountText = (i: Info) => `${i.amount_varies ? 'ca. ' : ''}${formatMoney(i.amount)}`;

  function suggestionBody(s: Suggestion, status = 'active') {
    return {
      name: s.name.trim() || 'Zahlung',
      match_key: s.match_key,
      direction: s.direction,
      interval: s.interval,
      amount_min: s.amount_min,
      amount_max: s.amount_max,
      category_id: s.category_id,
      status
    };
  }

  async function accept(s: Suggestion, status = 'active') {
    busy = true;
    try {
      await api.post('/api/recurring', suggestionBody(s, status));
      await load();
    } catch (e) {
      error = (e as Error).message;
    } finally {
      busy = false;
    }
  }

  async function acceptAll() {
    if (!data) return;
    busy = true;
    try {
      for (const s of data.suggestions) await api.post('/api/recurring', suggestionBody(s));
      await load();
    } finally {
      busy = false;
    }
  }

  async function toggle(i: Item) {
    if (open === i.id) {
      open = null;
      return;
    }
    open = i.id;
    edit = { name: i.name, interval: i.interval, category_id: i.category_id, status: i.status, note: i.note };
    txs = await api.get<Tx[]>(`/api/recurring/${i.id}/transactions`);
  }

  async function save(id: number) {
    if (!edit) return;
    await api.put(`/api/recurring/${id}`, edit);
    open = null;
    await load();
  }

  async function remove(i: Item) {
    if (!confirm(`„${i.name}“ entfernen? Die Zahlungen werden dann wieder als Vorschlag erkannt.`)) return;
    await api.del(`/api/recurring/${i.id}`);
    open = null;
    await load();
  }

  async function addCategory(kind: Category['kind']): Promise<number | null> {
    const name = prompt('Name der neuen Kategorie');
    if (!name?.trim()) return null;
    const c = await api.post<Category>('/api/categories', { name: name.trim(), kind });
    await load();
    return c.id;
  }

  async function onCategory(e: Event, target: { category_id: number | null }, kind: Category['kind']) {
    const value = (e.currentTarget as HTMLSelectElement).value;
    if (value === 'new') {
      target.category_id = await addCategory(kind);
    } else {
      target.category_id = value ? Number(value) : null;
    }
  }

  const kindLabel: Record<string, string> = { expense: 'Ausgaben', income: 'Einnahmen', transfer: 'Sparen & Umbuchungen' };
  const active = $derived((data?.items ?? []).filter((i) => i.status === 'active'));
  const ended = $derived((data?.items ?? []).filter((i) => i.status !== 'active'));
  const groups = $derived.by(() => {
    const out: { title: string; items: Item[]; monthly: number }[] = [];
    const expense = active.filter((i) => i.direction === 'out' && i.category_kind !== 'transfer');
    const cats = [...new Set(expense.map((i) => i.category ?? 'Ohne Kategorie'))];
    for (const c of cats) {
      const items = expense.filter((i) => (i.category ?? 'Ohne Kategorie') === c);
      out.push({ title: c, items, monthly: items.reduce((s, i) => s + toNumber(i.monthly), 0) });
    }
    out.sort((a, b) => b.monthly - a.monthly);
    const savings = active.filter((i) => i.category_kind === 'transfer');
    if (savings.length) out.push({ title: kindLabel.transfer, items: savings, monthly: savings.reduce((s, i) => s + toNumber(i.monthly), 0) });
    const income = active.filter((i) => i.direction === 'in' && i.category_kind !== 'transfer');
    if (income.length) out.push({ title: kindLabel.income, items: income, monthly: income.reduce((s, i) => s + toNumber(i.monthly), 0) });
    return out;
  });
  const catItems = $derived((data?.by_category ?? []).map((c) => ({ key: c.name, label: c.name, value: toNumber(c.monthly) })));
  const kindOf = (dir: string): Category['kind'] => (dir === 'in' ? 'income' : 'expense');
  const categoriesFor = (dir: string) => (data?.categories ?? []).filter((c) => c.kind === kindOf(dir) || c.kind === 'transfer');
</script>

<svelte:head><title>Verträge – Finanzen</title></svelte:head>

<div class="stack">
  <h1>Verträge & Abos</h1>
  <p class="muted">Finanzen sucht in euren Umsätzen nach Zahlungen, die regelmäßig wiederkommen – Miete, Versicherungen, Abos, Kredite, Gehalt – und ordnet sie Kategorien zu.</p>
  {#if error}<p class="error">{error}</p>{/if}

  {#if data && !data.has_transactions}
    <div class="card stack">
      <p class="muted">Noch keine Umsätze. Ruf deine Girokonten unter <a href="/banken">Banken</a> ab oder importiere eine CSV unter <a href="/import">Import</a> – am besten ein Jahr zurück, dann findet Finanzen auch jährliche Zahlungen.</p>
    </div>
  {/if}

  {#if data?.items.length}
    <section class="hero card">
      <div><span class="muted">Fixkosten im Monat</span><strong class="big"><Money value={data.summary.costs} cents={false} /></strong></div>
      <div><span class="muted">Regelmäßige Einnahmen</span><strong><Money value={data.summary.income} cents={false} /></strong></div>
      <div><span class="muted">Sparraten</span><strong><Money value={data.summary.savings} cents={false} /></strong></div>
      <div><span class="muted">Bleibt frei</span><strong><Money value={data.summary.free} cents={false} colored /></strong></div>
    </section>
  {/if}

  {#if data?.suggestions.length}
    <section class="card stack">
      <div class="row head">
        <h2>Neu erkannt <span class="muted">({data.suggestions.length})</span></h2>
        <button class="btn" onclick={acceptAll} disabled={busy}>Alle übernehmen</button>
      </div>
      <p class="muted small">Prüf Name und Kategorie und übernimm, was ein Vertrag ist. Ignorierte Vorschläge kommen nicht wieder.</p>
      {#each data.suggestions as s (s.match_key + s.direction + s.amount_min)}
        <div class="sugg">
          <div class="stack tight">
            <input bind:value={s.name} aria-label="Name" maxlength="120" />
            <span class="muted small ellipsis" title={s.example}>{s.example || '–'}</span>
          </div>
          <div class="stack tight">
            <strong class:pos={s.direction === 'in'}>{s.direction === 'in' ? '+' : '−'}{amountText(s)}</strong>
            <span class="muted small">{s.interval_label} · {s.count}× seit {formatDate(s.first_date)}</span>
          </div>
          <select value={s.category_id ?? ''} onchange={(e) => onCategory(e, s, kindOf(s.direction))} aria-label="Kategorie">
            <option value="">– ohne –</option>
            {#each categoriesFor(s.direction) as c (c.id)}<option value={c.id}>{c.name}</option>{/each}
            <option value="new">Neue Kategorie …</option>
          </select>
          <div class="row actions">
            <button class="btn primary" onclick={() => accept(s)} disabled={busy}>Übernehmen</button>
            <button class="btn" onclick={() => accept(s, 'ignored')} disabled={busy}>Ignorieren</button>
          </div>
        </div>
      {/each}
    </section>
  {/if}

  {#if data && (catItems.length || data.upcoming.length)}
    <div class="split">
      {#if catItems.length}
        <section class="card stack">
          <h2>Fixkosten nach Kategorie</h2>
          <BarList items={catItems} format={eur} money />
        </section>
      {/if}
      {#if data.upcoming.length}
        <section class="card stack">
          <h2>Demnächst fällig</h2>
          <ul class="list">
            {#each data.upcoming as u (u.id)}
              <li>
                <span class="date">{formatDate(u.date)}</span>
                <span class="grow ellipsis">{u.name}{#if u.overdue} <span class="badge warn">ausgeblieben</span>{/if}</span>
                <Money value={u.direction === 'in' ? u.amount : -toNumber(u.amount)} colored />
              </li>
            {/each}
          </ul>
        </section>
      {/if}
    </div>
  {/if}

  {#each groups as g (g.title)}
    <section class="card stack">
      <div class="row head">
        <h2>{g.title}</h2>
        <span class="muted small"><Money value={g.monthly} /> im Monat</span>
      </div>
      <ul class="items">
        {#each g.items as i (i.id)}
          {@render row(i)}
        {/each}
      </ul>
    </section>
  {/each}

  {#if ended.length}
    <section class="card stack">
      <button class="link" onclick={() => (showEnded = !showEnded)}>{showEnded ? 'Beendete ausblenden' : `${ended.length} beendet`}</button>
      {#if showEnded}
        <ul class="items">
          {#each ended as i (i.id)}{@render row(i)}{/each}
        </ul>
      {/if}
    </section>
  {/if}
</div>

{#snippet row(i: Item)}
  <li class:open={open === i.id}>
    <button class="item" onclick={() => toggle(i)} aria-expanded={open === i.id}>
      <span class="grow">
        <strong class="ellipsis">{i.name}</strong>
        <span class="muted small">
          {i.interval_label}{i.account ? ` · ${i.account}` : ''}{i.next_date && i.status === 'active' ? ` · nächste ${formatDate(i.next_date)}` : ''}
        </span>
        {#if i.changed}<span class="badge warn">Betrag geändert: {formatMoney(i.changed.from)} → {formatMoney(i.changed.to)}</span>{/if}
        {#if i.overdue && i.status === 'active'}<span class="badge warn">ausgeblieben – gekündigt?</span>{/if}
        {#if i.status === 'ended'}<span class="badge">beendet</span>{/if}
      </span>
      <span class="amounts">
        <strong class="money num" class:pos={i.direction === 'in'}>{i.direction === 'in' ? '+' : '−'}{amountText(i)}</strong>
        {#if i.interval !== 'monthly'}<span class="muted small"><Money value={i.monthly} /> / Monat</span>{/if}
      </span>
    </button>
    {#if open === i.id && edit}
      <div class="edit stack">
        <div class="grid">
          <label>Name <input bind:value={edit.name} maxlength="120" /></label>
          <label>
            Kategorie
            <select value={edit.category_id ?? ''} onchange={(e) => edit && onCategory(e, edit, kindOf(i.direction))}>
              <option value="">– ohne –</option>
              {#each categoriesFor(i.direction) as c (c.id)}<option value={c.id}>{c.name}</option>{/each}
              <option value="new">Neue Kategorie …</option>
            </select>
          </label>
          <label>
            Rhythmus
            <select bind:value={edit.interval}>
              {#each data?.intervals ?? [] as iv (iv.key)}<option value={iv.key}>{iv.label}</option>{/each}
            </select>
          </label>
          <label>
            Status
            <select bind:value={edit.status}>
              <option value="active">läuft</option>
              <option value="ended">beendet / gekündigt</option>
              <option value="ignored">kein Vertrag (ignorieren)</option>
            </select>
          </label>
          <label class="wide">Notiz <input bind:value={edit.note} placeholder="z. B. Kündigungsfrist 3 Monate, Vertragsnummer" maxlength="2000" /></label>
        </div>
        <div class="row">
          <button class="btn primary" onclick={() => save(i.id)}>Speichern</button>
          <button class="btn" onclick={() => (open = null)}>Abbrechen</button>
          <span class="grow"></span>
          <button class="btn danger" onclick={() => remove(i)}>Entfernen</button>
        </div>
        {#if txs.length}
          <div class="table-wrap">
            <table class="small">
              <tbody>
                {#each txs as t (t.id)}
                  <tr>
                    <td>{formatDate(t.date)}</td>
                    <td class="r"><Money value={t.amount} colored /></td>
                    <td class="muted purpose">{t.purpose}</td>
                  </tr>
                {/each}
              </tbody>
            </table>
          </div>
        {/if}
      </div>
    {/if}
  </li>
{/snippet}

<style>
  h1,
  h2 {
    margin: 0;
  }
  .small {
    font-size: 0.85rem;
    margin: 0;
  }
  .tight {
    gap: 2px;
  }
  .head {
    justify-content: space-between;
    align-items: center;
    flex-wrap: wrap;
  }
  .grow {
    flex: 1;
    min-width: 0;
  }
  .ellipsis {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    display: block;
  }
  .pos {
    color: var(--pos);
  }
  .hero {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(min(160px, 100%), 1fr));
    gap: 16px;
    align-items: end;
  }
  .hero div {
    display: grid;
  }
  .hero span {
    font-size: 0.85rem;
  }
  .hero strong {
    font-size: 1.1rem;
    font-variant-numeric: tabular-nums;
  }
  .hero .big {
    font-size: 1.8rem;
    line-height: 1.1;
  }
  .split {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(min(300px, 100%), 1fr));
    gap: 16px;
  }
  .sugg {
    display: grid;
    grid-template-columns: minmax(0, 1.6fr) minmax(0, 1fr) minmax(0, 1.2fr) auto;
    gap: 10px;
    align-items: center;
    padding: 10px 0;
    border-top: 1px solid var(--border);
  }
  .actions {
    flex-wrap: nowrap;
  }
  .list,
  .items {
    list-style: none;
    margin: 0;
    padding: 0;
  }
  .list li {
    display: flex;
    gap: 10px;
    align-items: center;
    padding: 6px 0;
    border-top: 1px solid var(--border);
  }
  .date {
    font-variant-numeric: tabular-nums;
    color: var(--muted);
    width: 88px;
    flex-shrink: 0;
  }
  .items li {
    border-top: 1px solid var(--border);
  }
  .item {
    display: flex;
    gap: 12px;
    align-items: center;
    width: 100%;
    padding: 10px 0;
    border: 0;
    background: none;
    color: inherit;
    font: inherit;
    text-align: left;
    cursor: pointer;
  }
  .item .grow {
    display: grid;
    gap: 2px;
  }
  .amounts {
    display: grid;
    justify-items: end;
    text-align: right;
    flex-shrink: 0;
  }
  .badge {
    display: inline-block;
    width: fit-content;
    font-size: 0.75rem;
    padding: 1px 8px;
    border-radius: 999px;
    background: var(--surface-2);
    color: var(--muted);
  }
  .badge.warn {
    color: var(--warn);
  }
  .edit {
    padding: 4px 0 14px;
  }
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
    gap: 12px;
  }
  .wide {
    grid-column: 1 / -1;
  }
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
    white-space: nowrap;
  }
  td.purpose {
    white-space: normal;
    min-width: 200px;
  }
  .r {
    text-align: right;
  }
  .link {
    background: none;
    border: 0;
    padding: 0;
    color: var(--accent-strong);
    cursor: pointer;
    font: inherit;
    width: fit-content;
  }
  @media (max-width: 760px) {
    .sugg {
      grid-template-columns: minmax(0, 1fr) auto;
    }
    .sugg select {
      grid-column: 1 / -1;
    }
    .sugg .actions {
      grid-column: 1 / -1;
    }
  }
</style>
