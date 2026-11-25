<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '#lib/api.ts';
  import BudgetTabs from '#lib/BudgetTabs.svelte';
  import BarList from '#lib/charts/BarList.svelte';
  import { formatDate, formatMoney, toNumber } from '#lib/format.ts';
  import Money from '#lib/Money.svelte';
  import RuleEditor, { type Rule } from '#lib/RuleEditor.svelte';

  interface MonthRow {
    month: string;
    income: string;
    expenses: string;
    savings: string;
    savings_rate: number | null;
    rest: string;
    internal: string;
  }
  interface Entry {
    name: string;
    amount: string;
    bookings: Booking[];
  }
  type Section = 'expenses' | 'savings' | 'income';
  interface FlowAccount {
    id: number;
    name: string;
    kind: string;
    role: 'spending' | 'saving';
    automatic: boolean;
  }
  interface Booking {
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
  interface Cashflow {
    months: MonthRow[];
    month: string;
    detail: {
      income: Entry[];
      expenses: Entry[];
      savings: Entry[];
      uncategorized: Booking[];
    };
    accounts: FlowAccount[];
    unknown_groups: { pattern: string; count: number; total: string; example: string; purpose: string; last: string }[];
  }
  interface SavedRule extends Rule {
    id: number;
    category: string | null;
    count: number;
    total: string;
  }
  interface CategoryOption {
    id: number;
    name: string;
    kind: string;
  }

  let data = $state<Cashflow | null>(null);
  let rules = $state<SavedRule[]>([]);
  let categories = $state<CategoryOption[]>([]);
  let editing = $state<{ key: string; rule: Rule } | null>(null);
  let showRules = $state(false);
  let selected = $state<string | null>(null);
  let error = $state('');
  // category (or savings route) whose single bookings are shown; kept by name when the month changes
  let opened = $state<{ section: Section; name: string } | null>(null);
  const openEntry = $derived(opened && data ? (data.detail[opened.section].find((e) => e.name === opened!.name) ?? null) : null);
  const toggle = (section: Section, name: string) =>
    (opened = opened?.section === section && opened.name === name ? null : { section, name });
  const KIND_LABEL: Record<string, string> = { expense: 'Ausgaben', income: 'Einnahmen', transfer: 'Sparen & Anlegen', internal: 'Umbuchungen' };
  const categoryGroups = $derived(
    Object.entries(KIND_LABEL)
      .map(([kind, label]) => ({ label, items: categories.filter((c) => c.kind === kind) }))
      .filter((g) => g.items.length)
  );
  let saving = $state<number | null>(null);
  async function assign(b: Booking, value: string) {
    saving = b.id;
    try {
      await api.put(`/api/transactions/${b.id}/category`, { category_id: value === '' ? null : Number(value) });
      await load(selected);
    } catch (e) {
      error = (e as Error).message;
    } finally {
      saving = null;
    }
  }
  const SOURCE_HINT: Record<string, string> = { rule: 'per Regel', keyword: 'automatisch erkannt' };
  const SECTION_LABEL: Record<Section, string> = { expenses: 'Ausgaben', savings: 'Gespart', income: 'Einnahmen' };

  async function load(month: string | null = selected) {
    try {
      data = await api.get<Cashflow>(`/api/cashflow?months=12${month ? `&month=${month}` : ''}`);
      selected = data.month;
    } catch (e) {
      error = (e as Error).message;
    }
  }
  async function loadRules() {
    [rules, categories] = await Promise.all([api.get<SavedRule[]>('/api/category-rules'), api.get<CategoryOption[]>('/api/categories')]);
  }
  onMount(() => {
    load(null);
    loadRules();
  });

  async function afterSave() {
    editing = null;
    await Promise.all([load(), loadRules()]);
  }

  async function removeRule(r: SavedRule) {
    if (!confirm(`Regel „${r.pattern}“ → ${r.category} löschen?`)) return;
    await api.del(`/api/category-rules/${r.id}`);
    await Promise.all([load(), loadRules()]);
  }

  const newRule = (pattern: string): Rule => ({ pattern, field: 'any', direction: 'out', account_id: null, category_id: null });
  const expenseCategories = $derived(categories.filter((c) => c.kind === 'expense' || c.kind === 'transfer' || c.kind === 'internal'));
  const fieldText = { any: '', counterparty: ' im Empfänger', purpose: ' im Zweck' };

  const MONTHS = ['Jan', 'Feb', 'Mär', 'Apr', 'Mai', 'Jun', 'Jul', 'Aug', 'Sep', 'Okt', 'Nov', 'Dez'];
  const monthLabel = (m: string, long = false) => {
    const name = MONTHS[Number(m.slice(5)) - 1];
    return long ? `${name} ${m.slice(0, 4)}` : `${name} ${m.slice(2, 4)}`;
  };
  const current = $derived(data?.months.find((m) => m.month === selected) ?? null);
  const withIncome = $derived((data?.months ?? []).filter((m) => toNumber(m.income) > 0));
  const avgRate = $derived.by(() => {
    const inc = withIncome.reduce((s, m) => s + toNumber(m.income), 0);
    const sav = withIncome.reduce((s, m) => s + toNumber(m.savings), 0);
    return inc > 0 ? sav / inc : null;
  });
  const pct = (v: number | null) => (v === null ? '–' : `${(v * 100).toLocaleString('de-DE', { maximumFractionDigits: 0 })} %`);
  const eur = (v: number) => formatMoney(v, 'EUR', false);

  // grouped bars: income, expenses, savings per month (fixed series order = fixed colors)
  const SERIES = [
    { key: 'income', label: 'Einnahmen', color: 'var(--series-3)' },
    { key: 'expenses', label: 'Ausgaben', color: 'var(--series-2)' },
    { key: 'savings', label: 'Gespart', color: 'var(--series-1)' }
  ] as const;
  let width = $state(0);
  const W = $derived(width || 760);
  const H = 260;
  const pad = $derived({ l: W < 500 ? 52 : 64, r: 4, t: 12, b: 28 });
  const maxV = $derived(Math.max(1, ...(data?.months ?? []).flatMap((m) => [toNumber(m.income), toNumber(m.expenses), Math.abs(toNumber(m.savings))])));
  const minV = $derived(Math.min(0, ...(data?.months ?? []).map((m) => toNumber(m.savings))));
  const yTicks = $derived.by(() => {
    const span = maxV - minV;
    const raw = span / 4;
    const mag = Math.pow(10, Math.floor(Math.log10(raw || 1)));
    const step = [1, 2, 2.5, 5, 10].map((k) => k * mag).find((s) => s >= raw) ?? raw;
    const out: number[] = [];
    for (let v = Math.ceil(minV / step) * step; v <= maxV + 1e-9; v += step) out.push(Math.round(v / step) * step + 0);
    return [...new Set(out)];
  });
  const lo = $derived(Math.min(minV, yTicks[0] ?? 0));
  const hi = $derived(Math.max(maxV, yTicks[yTicks.length - 1] ?? maxV));
  const sy = (v: number) => pad.t + (1 - (v - lo) / (hi - lo || 1)) * (H - pad.t - pad.b);
  const groupW = $derived((W - pad.l - pad.r) / Math.max(1, data?.months.length ?? 1));
  const barW = $derived(Math.max(3, Math.min(16, (groupW - 10) / 3 - 2)));
</script>

{#snippet categoryCell(b: Booking)}
  <td class="cat">
    {#if b.assignable}
      <select
        aria-label="Kategorie für {b.counterparty || b.purpose}"
        value={b.category_source === 'fixed' ? String(b.category_id) : ''}
        disabled={saving === b.id}
        onchange={(e) => assign(b, (e.currentTarget as HTMLSelectElement).value)}
      >
        <option value="">Automatisch{b.category_source && b.category_source !== 'fixed' ? ` (${categories.find((c) => c.id === b.category_id)?.name ?? '?'})` : ''}</option>
        {#each categoryGroups as g (g.label)}
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
{/snippet}

<svelte:head><title>Monatsbilanz – Finanzen</title></svelte:head>

<div class="stack">
  <h1>Monatsbilanz</h1>
  <BudgetTabs />
  <p class="muted">
    Was kam rein, was ging raus, was habt ihr gespart – aus den echten Buchungen. Gespart ist, was von den Haushaltskonten auf Sparkonten fließt
    (abzüglich Entnahmen) plus direkte Sparbeiträge wie Riester oder Sparpläne. Geld zwischen Konten derselben Art zählt nicht. Welche Konten
    Haushaltskonten sind, legst du unter <a href="/konten">Konten</a> fest.
  </p>
  {#if error}<p class="error">{error}</p>{/if}

  {#if data}
    <section class="card stack">
      <div class="row head">
        <h2>Letzte 12 Monate</h2>
        <span class="muted small">Ø Sparquote {pct(avgRate)}</span>
      </div>
      <ul class="legend small">
        {#each SERIES as s (s.key)}<li><span class="swatch" style:background={s.color}></span>{s.label}</li>{/each}
      </ul>
      <div class="chart" bind:clientWidth={width}>
      {#if width > 0}
      <svg width={W} height={H} class="bars" role="img" aria-label="Einnahmen, Ausgaben und Gespartes je Monat">
        {#each yTicks as t, ti (ti)}
          <line x1={pad.l} x2={W - pad.r} y1={sy(t)} y2={sy(t)} class="grid" class:zero={t === 0} />
          <text x={pad.l - 6} y={sy(t)} text-anchor="end" dominant-baseline="middle" class="tick money">{eur(t)}</text>
        {/each}
        {#each data.months as m, k (m.month)}
          {@const x0 = pad.l + k * groupW + (groupW - 3 * barW - 4) / 2}
          <g class="month" class:sel={m.month === selected} role="button" tabindex="0" aria-label="{monthLabel(m.month, true)} anzeigen" onclick={() => load(m.month)} onkeydown={(e) => e.key === 'Enter' && load(m.month)}>
            <title>{monthLabel(m.month, true)}: Einnahmen {formatMoney(m.income)}, Ausgaben {formatMoney(m.expenses)}, gespart {formatMoney(m.savings)}</title>
            <rect x={pad.l + k * groupW} y={pad.t} width={groupW} height={H - pad.t - pad.b} class="hit" />
            {#each SERIES as s, j (s.key)}
              {@const v = toNumber(m[s.key])}
              <rect x={x0 + j * (barW + 2)} y={Math.min(sy(v), sy(0))} width={barW} height={Math.max(1, Math.abs(sy(v) - sy(0)))} rx="3" fill={s.color} />
            {/each}
            {#if groupW >= 44 || k % 2 === (data.months.length - 1) % 2}
              <text x={pad.l + k * groupW + groupW / 2} y={H - 8} text-anchor="middle" class="tick" class:strong={m.month === selected}>{groupW >= 44 ? monthLabel(m.month) : MONTHS[Number(m.month.slice(5)) - 1]}</text>
            {/if}
          </g>
        {/each}
      </svg>
      {/if}
      </div>
      <p class="muted small">Tipp: Monat antippen, um ihn unten im Detail zu sehen.</p>
    </section>

    {#if current}
      <section class="card stack">
        <h2>{monthLabel(current.month, true)}</h2>
        <div class="tiles">
          <div><span class="muted">Einnahmen</span><strong><Money value={current.income} cents={false} /></strong></div>
          <div><span class="muted">Ausgaben</span><strong><Money value={current.expenses} cents={false} /></strong></div>
          <div><span class="muted">Gespart</span><strong><Money value={current.savings} cents={false} colored /></strong></div>
          <div><span class="muted">Sparquote</span><strong>{pct(current.savings_rate)}</strong></div>
          <div>
            <span class="muted" title="Einnahmen minus Ausgaben minus Gespartes – das, was auf den Alltagskonten mehr (oder weniger) geworden ist">Übrig</span>
            <strong><Money value={current.rest} cents={false} colored /></strong>
          </div>
        </div>
        <div class="split">
          <div>
            <h3>Ausgaben nach Kategorie</h3>
            {#if data.detail.expenses.length}
              <BarList
                items={data.detail.expenses.map((e) => ({ key: e.name, label: e.name, value: toNumber(e.amount) }))}
                format={eur}
                money
                selected={opened?.section === 'expenses' ? opened.name : null}
                onselect={(k) => toggle('expenses', k)}
              />
            {:else}<p class="muted small">Keine Ausgaben.</p>{/if}
          </div>
          <div class="stack">
            <div>
              <h3>Gespart</h3>
              <ul class="list">
                {#each data.detail.savings as s (s.name)}
                  <li>
                    <button class="entry" class:on={opened?.section === 'savings' && opened.name === s.name} onclick={() => toggle('savings', s.name)}>{s.name}</button>
                    <Money value={s.amount} cents={false} colored />
                  </li>
                {/each}
                {#if !data.detail.savings.length}<li class="muted">Nichts gespart.</li>{/if}
              </ul>
            </div>
            <div>
              <h3>Einnahmen</h3>
              <ul class="list">
                {#each data.detail.income as s (s.name)}
                  <li>
                    <button class="entry" class:on={opened?.section === 'income' && opened.name === s.name} onclick={() => toggle('income', s.name)}>{s.name}</button>
                    <Money value={s.amount} cents={false} />
                  </li>
                {/each}
                {#if !data.detail.income.length}<li class="muted">Keine Einnahmen.</li>{/if}
              </ul>
            </div>
          </div>
        </div>
        {#if opened}
          <div class="bookings stack">
            <div class="row head">
              <h3>
                {opened.name} <span class="muted small">· {SECTION_LABEL[opened.section]} {monthLabel(data.month, true)}</span>
              </h3>
              <button class="link small" onclick={() => (opened = null)}>Schließen</button>
            </div>
            {#if openEntry}
              <div class="table-wrap">
                <table class="small">
                  <tbody>
                    {#each openEntry.bookings as b, i (`${b.id}-${i}`)}
                      <tr>
                        <td class="nowrap">{formatDate(b.date)}</td>
                        <td class="r nowrap"><Money value={b.amount} /></td>
                        <td>{b.counterparty || '–'}<div class="muted purpose-cell">{b.purpose}</div></td>
                        <td class="muted">{b.account}</td>
                        {@render categoryCell(b)}
                      </tr>
                    {/each}
                  </tbody>
                </table>
              </div>
              <p class="muted small">{openEntry.bookings.length} Buchung{openEntry.bookings.length === 1 ? '' : 'en'} · Summe <Money value={openEntry.amount} /></p>
            {:else}
              <p class="muted small">In diesem Monat keine Buchungen.</p>
            {/if}
          </div>
        {/if}
        {#if data.detail.uncategorized.length}
          <details>
            <summary class="small">Größte Ausgaben ohne Kategorie</summary>
            <div class="table-wrap">
              <table class="small">
                <tbody>
                  {#each data.detail.uncategorized as u, i (i)}
                    <tr>
                      <td>{formatDate(u.date)}</td>
                      <td class="r"><Money value={u.amount} /></td>
                      <td>{u.counterparty}<div class="muted purpose-cell">{u.purpose}</div></td>
                      <td class="muted">{u.account}</td>
                      {@render categoryCell(u)}
                    </tr>
                  {/each}
                </tbody>
              </table>
            </div>
          </details>
        {/if}
      </section>
    {/if}

    <section class="card stack">
      <h2>Ohne Kategorie</h2>
      {#if data.unknown_groups.length}
        <p class="muted small">Die häufigsten Ausgaben der letzten zwölf Monate, die noch keiner Kategorie zugeordnet sind. Leg eine Regel an – sie gilt auch für alle künftigen Buchungen.</p>
        <ul class="groups">
          {#each data.unknown_groups as g (g.pattern)}
            <li>
              <div class="grow">
                <strong class="ellipsis">{g.example}</strong>
                {#if g.purpose && g.purpose !== g.example}<span class="small ellipsis purpose" title={g.purpose}>{g.purpose}</span>{/if}
                <span class="muted small">{g.count}× · zuletzt {formatDate(g.last)}</span>
              </div>
              <Money value={g.total} cents={false} />
              <button class="btn" onclick={() => (editing = { key: g.pattern, rule: newRule(g.pattern) })}>Kategorie festlegen</button>
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
        <button class="link" onclick={() => (showRules = !showRules)}>{showRules ? 'Regeln ausblenden' : `Regeln (${rules.length})`}</button>
        <button class="btn" onclick={() => ((showRules = true), (editing = { key: 'new', rule: newRule('') }))}>Neue Regel</button>
      </div>
      {#if editing?.key === 'new'}
        <RuleEditor rule={editing.rule} categories={categories} onsaved={afterSave} oncancel={() => (editing = null)} />
      {/if}
      {#if showRules}
        <p class="muted small">Die erste passende Regel gewinnt, längere (genauere) Muster zuerst. Kategorien aus „Verträge“ gehen immer vor; ohne Regel ordnet Finanzen bekannte Händler selbst zu.</p>
        <ul class="groups">
          {#each rules as r (r.id)}
            <li>
              <div class="grow">
                <span>enthält „<strong>{r.pattern}</strong>“{fieldText[r.field]}{r.direction === 'in' ? ' (Einnahmen)' : r.direction === 'any' ? '' : ''} → <strong>{r.category}</strong></span>
                <span class="muted small">{r.count} Buchungen · {formatMoney(r.total, 'EUR', false)}</span>
              </div>
              <button class="btn" onclick={() => (editing = { key: `r${r.id}`, rule: { ...r } })}>Ändern</button>
              <button class="btn danger" onclick={() => removeRule(r)}>Löschen</button>
            </li>
            {#if editing?.key === `r${r.id}`}
              <li class="edit"><RuleEditor rule={editing.rule} categories={categories} onsaved={afterSave} oncancel={() => (editing = null)} /></li>
            {/if}
          {/each}
          {#if !rules.length}<li class="muted small">Noch keine eigenen Regeln.</li>{/if}
        </ul>
      {/if}
    </section>
  {/if}
</div>

<style>
  h1,
  h2,
  h3 {
    margin: 0;
  }
  h3 {
    font-size: 1rem;
    margin-bottom: 8px;
  }
  .small {
    font-size: 0.85rem;
  }
  p.small {
    margin: 0;
  }
  .head {
    justify-content: space-between;
    align-items: center;
  }
  .legend {
    display: flex;
    gap: 16px;
    list-style: none;
    margin: 0;
    padding: 0;
  }
  .swatch {
    display: inline-block;
    width: 10px;
    height: 10px;
    border-radius: 3px;
    margin-right: 6px;
  }
  .chart {
    width: 100%;
    min-height: 260px;
  }
  .bars {
    display: block;
  }
  .grid {
    stroke: var(--grid);
  }
  .grid.zero {
    stroke: var(--muted);
    opacity: 0.6;
  }
  .tick {
    fill: var(--muted);
    font-size: 12px;
  }
  .tick.strong {
    fill: var(--text);
    font-weight: 600;
  }
  .hit {
    fill: transparent;
  }
  .month {
    cursor: pointer;
  }
  .month:hover .hit,
  .month.sel .hit {
    fill: var(--surface-2);
  }
  .month:focus-visible {
    outline: 2px solid var(--accent);
  }
  .tiles {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(min(130px, 100%), 1fr));
    gap: 16px;
  }
  .tiles div {
    display: grid;
  }
  .tiles span {
    font-size: 0.85rem;
  }
  .tiles strong {
    font-size: 1.2rem;
    font-variant-numeric: tabular-nums;
  }
  .split {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(min(300px, 100%), 1fr));
    gap: 24px;
  }
  .list {
    list-style: none;
    margin: 0;
    padding: 0;
  }
  .entry {
    background: none;
    border: 0;
    padding: 0;
    font: inherit;
    color: inherit;
    text-align: left;
    cursor: pointer;
  }
  .entry:hover,
  .entry.on {
    text-decoration: underline;
  }
  .entry.on {
    font-weight: 600;
  }
  .bookings {
    border-top: 1px solid var(--border);
    padding-top: 12px;
  }
  .bookings h3 {
    margin: 0;
  }
  .cat select {
    max-width: 220px;
    font-size: 0.85rem;
  }
  .hint {
    font-size: 0.75rem;
  }
  .nowrap {
    white-space: nowrap;
  }
  .list li {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 12px;
    padding: 6px 0;
    border-top: 1px solid var(--border);
  }
  .groups {
    list-style: none;
    margin: 0;
    padding: 0;
  }
  .groups li {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 8px 0;
    border-top: 1px solid var(--border);
    flex-wrap: wrap;
  }
  .groups li.edit {
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
  .purpose {
    color: var(--muted);
  }
  .purpose-cell {
    font-size: 0.8rem;
    white-space: normal;
  }
  .link {
    background: none;
    border: 0;
    padding: 0;
    color: var(--accent-strong);
    cursor: pointer;
    font: inherit;
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
  }
  .r {
    text-align: right;
    white-space: nowrap;
  }
</style>
