<script lang="ts">
  // Compact return block for the overview: one line of key figures and the best and weakest positions.
  import Term from './Term.svelte';
  import { api } from './api.ts';
  import { formatPercent, toNumber } from './format.ts';
  import Money from './Money.svelte';
  import PeriodPicker from './PeriodPicker.svelte';
  import { flattenBreakdown, rankByIrr, type Breakdown } from './returns.ts';

  let {
    personId = null,
    period = $bindable('1Y'),
    showPeriod = true
  }: { personId?: number | null; period?: string; showPeriod?: boolean } = $props();
  let data = $state<Breakdown | null>(null);

  $effect(() => {
    const p = period;
    const person = personId;
    api
      .get<Breakdown>(`/api/performance/breakdown?period=${p}${person !== null ? `&person_id=${person}` : ''}`)
      .then((d) => (data = d))
      .catch(() => (data = null));
  });

  const ranked = $derived(rankByIrr(flattenBreakdown(data?.items ?? [])).filter((r) => r.irr !== null));
  const best = $derived(ranked.slice(0, 3));
  const worst = $derived(ranked.length > 3 ? ranked.slice(-Math.min(3, ranked.length - 3)).reverse() : []);
  const pc = (v: string | null | undefined) => (v === null || v === undefined ? null : toNumber(v) * 100);
  const pctText = (v: string | null | undefined) => {
    const n = pc(v);
    return n === null ? '–' : formatPercent(Math.abs(n) < 0.005 ? 0 : n);
  };
</script>

{#if data?.total}
  {@const t = data.total}
  <section class="card stack">
    <div class="row head">
      <h2><a href="/anlagen">Rendite eurer Anlagen</a></h2>
      {#if showPeriod}<PeriodPicker bind:value={period} />{/if}
    </div>
    <div class="kpis">
      <div><span class="muted">Gewinn</span><strong><Money value={t.gain} cents={false} colored /></strong></div>
      <div>
        <span class="muted"><Term term="izf" /></span>
        <strong class:pos={(pc(t.irr) ?? 0) > 0} class:neg={(pc(t.irr) ?? 0) < 0}>{pctText(t.irr)}</strong>
      </div>
      <div><span class="muted"><Term term="ttwror" /></span><strong>{pctText(t.ttwror_pa ?? t.ttwror)}</strong></div>
      <div><span class="muted">Eingesetzt (Ø)</span><strong><Money value={t.avg_capital} cents={false} /></strong></div>
    </div>
    {#if best.length}
      <div class="lists">
        {#each [{ title: 'Am besten', rows: best }, { title: 'Am schwächsten', rows: worst }] as col (col.title)}
          {#if col.rows.length}
            <div>
              <h3>{col.title}</h3>
              <ul>
                {#each col.rows as r (r.key)}
                  {@const v = pc(r.irr) ?? 0}
                  <li>
                    <span class="name"><a href={r.href}>{r.name}</a><span class="muted small">{r.sub}</span></span>
                    <span class="val">
                      <strong class:pos={v > 0} class:neg={v < 0}>{pctText(r.irr)}</strong>
                      <span class="small"><Money value={r.gain} cents={false} colored /></span>
                    </span>
                  </li>
                {/each}
              </ul>
            </div>
          {/if}
        {/each}
      </div>
    {/if}
    <a class="more small" href="/anlagen">Alle Anlagen, Zusammensetzung und Vergleich →</a>
  </section>
{/if}

<style>
  h2,
  h3 {
    margin: 0;
  }
  h2 a {
    color: inherit;
    text-decoration: none;
  }
  h2 a:hover {
    text-decoration: underline;
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
  .kpis {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(min(140px, 100%), 1fr));
    gap: 12px;
  }
  .kpis div {
    display: grid;
  }
  .kpis span {
    font-size: 0.85rem;
  }
  .kpis strong {
    font-size: 1.2rem;
    font-variant-numeric: tabular-nums;
  }
  .lists {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(min(280px, 100%), 1fr));
    gap: 12px 24px;
  }
  ul {
    list-style: none;
    margin: 0;
    padding: 0;
  }
  li {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 12px;
    padding: 6px 0;
    border-top: 1px solid var(--border);
  }
  .name {
    display: grid;
    min-width: 0;
  }
  .name a {
    color: inherit;
    text-decoration: none;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .name a:hover {
    text-decoration: underline;
  }
  .val {
    display: grid;
    justify-items: end;
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
  }
  .pos {
    color: var(--pos);
  }
  .neg {
    color: var(--neg);
  }
  .more {
    color: var(--accent-strong);
    width: fit-content;
  }
</style>
