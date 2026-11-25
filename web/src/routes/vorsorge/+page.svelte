<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '#lib/api.ts';
  import LineChart from '#lib/charts/LineChart.svelte';
  import DecimalInput from '#lib/DecimalInput.svelte';
  import { formatDate, formatMoney, toNumber } from '#lib/format.ts';
  import Money from '#lib/Money.svelte';
  import { household, loadPersons } from '#lib/persons.svelte.ts';

  interface Pension {
    account_id: number;
    name: string;
    product: string;
    product_label: string;
    start: string;
    nominal: number;
    monthly: number;
    after_retirement: boolean;
    statement_date: string | null;
    owner: string | null;
  }
  interface Scenario {
    key: string;
    label: string;
    return: number;
    capital: number;
    withdrawal: number;
    pensions: number;
    gross: number;
    health: number;
    income_tax: number;
    capital_tax: number;
    net: number;
    series: { date: string; value: number }[];
  }
  interface Projection {
    person_id: number | null;
    retire_on: string;
    default_retire_on: string;
    years_to_retirement: number;
    inputs: { savings: number; savings_default: number; inflation: number; years: number; returns: Record<string, number> };
    pensions: Pension[];
    capital: { account_id: number; name: string; kind: string; value: number; cost: number }[];
    capital_now: number;
    scenarios: Scenario[];
  }

  let personId = $state<number | null>(null); // null = whole household
  let retireOn = $state('');
  let savings = $state<string | null>('');
  let inflation = $state<string | null>('2');
  let years = $state<string | null>('25');
  let rLow = $state<string | null>('3');
  let rMid = $state<string | null>('5');
  let rHigh = $state<string | null>('7');
  let data = $state<Projection | null>(null);
  let error = $state('');
  let loading = $state(false);

  onMount(() => {
    loadPersons();
  });

  const num = (v: string | null | undefined) => (v == null || String(v).trim() === '' ? null : Number(String(v).replace(',', '.')));
  let timer: ReturnType<typeof setTimeout> | undefined;
  $effect(() => {
    const q = new URLSearchParams();
    if (personId !== null) q.set('person_id', String(personId));
    if (retireOn) q.set('retire_on', retireOn);
    const s = num(savings);
    if (s !== null && !Number.isNaN(s)) q.set('savings', String(s));
    const pairs: [string, string | null][] = [
      ['inflation', inflation],
      ['r_low', rLow],
      ['r_mid', rMid],
      ['r_high', rHigh]
    ];
    for (const [k, v] of pairs) {
      const n = num(v);
      if (n !== null && !Number.isNaN(n)) q.set(k, String(n / 100));
    }
    const y = num(years);
    if (y !== null && y >= 1) q.set('years', String(Math.round(y)));
    clearTimeout(timer);
    timer = setTimeout(async () => {
      loading = true;
      try {
        data = await api.get<Projection>(`/api/retirement?${q}`);
        error = '';
      } catch (e) {
        error = (e as Error).message;
      } finally {
        loading = false;
      }
    }, 300);
  });

  const COLORS: Record<string, string> = { vorsichtig: 'var(--series-2)', mittel: 'var(--series-1)', optimistisch: 'var(--series-3)' };
  const series = $derived(
    (data?.scenarios ?? []).map((s) => ({ key: s.key, label: s.label, color: COLORS[s.key] ?? 'var(--series-4)', points: s.series.map((p) => ({ date: p.date, value: p.value })) }))
  );
  const eur = (v: number) => formatMoney(v, 'EUR', false);
  const pct = (v: number) => `${(v * 100).toLocaleString('de-DE', { maximumFractionDigits: 1 })} %`;
</script>

<svelte:head><title>Altersvorsorge – Finanzen</title></svelte:head>

<div class="stack">
  <h1>Altersvorsorge</h1>

  <section class="card stack">
    <div class="inputs">
      <label>
        Person
        <select bind:value={personId}>
          <option value={null}>Ganzer Haushalt</option>
          {#each household.persons.filter((p) => !p.archived) as p (p.id)}<option value={p.id}>{p.name}</option>{/each}
        </select>
      </label>
      <label>
        Rentenbeginn
        <input type="date" bind:value={retireOn} />
        {#if data && !retireOn}<span class="muted small">{formatDate(data.default_retire_on)} ({personId === null ? 'wenn alle in Rente sind' : 'aus den Verträgen'})</span>{/if}
      </label>
      <label>
        Sparrate / Monat
        <DecimalInput bind:value={savings} suffix="€" />
        {#if data && !savings}<span class="muted small">{eur(data.inputs.savings_default)} aus den letzten 12 Monaten</span>{/if}
      </label>
      <label>Inflation <DecimalInput bind:value={inflation} suffix="%" /></label>
      <label>Entnahme über (Jahre) <DecimalInput bind:value={years} /></label>
    </div>
    <div class="inputs">
      <label>Rendite vorsichtig p. a. <DecimalInput bind:value={rLow} suffix="%" /></label>
      <label>Rendite mittel p. a. <DecimalInput bind:value={rMid} suffix="%" /></label>
      <label>Rendite optimistisch p. a. <DecimalInput bind:value={rHigh} suffix="%" /></label>
    </div>
  </section>

  {#if error}<p class="error">{error}</p>{/if}

  {#if data}
    <section class="card stack" aria-busy={loading}>
      <div class="row head">
        <h2>Monatliches Einkommen ab {formatDate(data.retire_on)}</h2>
        <span class="muted small">in heutiger Kaufkraft · in {data.years_to_retirement.toLocaleString('de-DE')} Jahren</span>
      </div>
      <div class="scenarios">
        {#each data.scenarios as s (s.key)}
          <div class="scenario" class:main={s.key === 'mittel'}>
            <span class="muted"><i class="dot" style:background={COLORS[s.key]}></i>{s.label} · {pct(s.return)}</span>
            <strong class="big"><Money value={s.net} cents={false} /></strong>
            <span class="small">netto geschätzt · brutto <Money value={s.gross} cents={false} /></span>
            <dl>
              <dt>Renten</dt><dd><Money value={s.pensions} cents={false} /></dd>
              <dt>Entnahme Kapital</dt><dd><Money value={s.withdrawal} cents={false} /></dd>
              <dt>Kranken-/Pflegevers.</dt><dd><Money value={s.health ? -s.health : 0} cents={false} /></dd>
              <dt>Einkommensteuer</dt><dd><Money value={s.income_tax ? -s.income_tax : 0} cents={false} /></dd>
              <dt>Abgeltungsteuer</dt><dd><Money value={s.capital_tax ? -s.capital_tax : 0} cents={false} /></dd>
              <dt>Kapital bei Rentenbeginn</dt><dd><strong><Money value={s.capital} cents={false} /></strong></dd>
            </dl>
          </div>
        {/each}
      </div>
    </section>

    <div class="split">
      <section class="card stack">
        <h2>Renten</h2>
        {#if data.pensions.length}
          <ul class="list">
            {#each data.pensions as p (p.account_id)}
              <li>
                <span class="name">
                  <a href="/konten/{p.account_id}">{p.name}</a>
                  <span class="muted small">
                    {#if personId === null && p.owner}{p.owner}{' · '}{/if}{p.product_label} · ab {formatDate(p.start)}{#if p.statement_date} · Stand {formatDate(p.statement_date)}{/if}{#if p.after_retirement} · beginnt später{/if}
                  </span>
                </span>
                <span class="val">
                  <Money value={p.monthly} cents={false} />
                  {#if p.product !== 'gesetzlich' && Math.abs(p.nominal - p.monthly) >= 1}<span class="muted small">nominal <Money value={p.nominal} cents={false} /></span>{/if}
                </span>
              </li>
            {/each}
          </ul>
        {:else}
          <p class="muted small">Noch keine Rente hinterlegt. Lade deine Renteninformation hoch oder trag bei einem Vorsorge-Vertrag die prognostizierte Rente ein.</p>
        {/if}
      </section>
      <section class="card stack">
        <div class="row head">
          <h2>Kapital heute</h2>
          <strong><Money value={data.capital_now} cents={false} /></strong>
        </div>
        <ul class="list">
          {#each data.capital as c (c.account_id)}
            <li><a href="/konten/{c.account_id}" class="name">{c.name}</a><Money value={c.value} cents={false} /></li>
          {/each}
          {#if !data.capital.length}<li class="muted small">Kein Kapital zugeordnet.</li>{/if}
        </ul>
      </section>
    </div>

    <section class="card stack">
      <h2>Vermögen bis zum Rentenbeginn</h2>
      {#if series.length && series[0].points.length > 1}
        <LineChart {series} format={eur} money ariaLabel="Hochgerechnetes Kapital bis zum Rentenbeginn in drei Szenarien" />
        <ul class="legend small">
          {#each data.scenarios as s (s.key)}<li><i class="dot" style:background={COLORS[s.key]}></i>{s.label}: <Money value={s.capital} cents={false} /></li>{/each}
        </ul>
      {/if}
    </section>

    <p class="muted small">
      Grobe Hochrechnung, keine Beratung. Alle Beträge in heutiger Kaufkraft. Die gesetzliche Rente stammt aus der Renteninformation (ohne
      künftige Rentenanpassungen, das entspricht etwa heutiger Kaufkraft); andere Renten sind nominal zugesagt und werden mit der Inflation abgezinst.
      Kapital sind Depots, Krypto, Tagesgeld, Festgeld, Beteiligungen und Verträge ohne Rentenprognose – ohne Haushaltskonten und Immobilien. Es wächst
      mit der Rendite des Szenarios und der Sparrate (Standard: euer Gespartes der letzten 12 Monate, anteilig) und wird ab Rentenbeginn über die gewählte Dauer verbraucht. Netto: Kranken- und
      Pflegeversicherung der Rentner auf gesetzliche und Betriebsrenten, Einkommensteuer je Person nach Grundtarif 2025 mit Besteuerungs- bzw. Ertragsanteil,
      Abgeltungsteuer auf den Gewinnanteil der Entnahmen. Ohne Splitting, Kirchensteuer und Freibeträge.
    </p>
  {:else if !error}
    <p class="muted">Lädt …</p>
  {/if}
</div>

<style>
  h1,
  h2 {
    margin: 0;
  }
  .head {
    justify-content: space-between;
    flex-wrap: wrap;
  }
  .small {
    font-size: 0.8rem;
  }
  p.small {
    margin: 0;
  }
  .inputs {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(min(170px, 100%), 1fr));
    gap: 12px 16px;
  }
  .inputs label {
    display: grid;
    gap: 4px;
    align-content: start;
  }
  .scenarios {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(min(220px, 100%), 1fr));
    gap: 16px;
  }
  .scenario {
    display: grid;
    gap: 4px;
    align-content: start;
    padding: 12px;
    border: 1px solid var(--border);
    border-radius: 10px;
  }
  .scenario.main {
    border-color: var(--accent);
    background: var(--accent-soft);
  }
  .big {
    font-size: 1.8rem;
    line-height: 1.1;
    font-variant-numeric: tabular-nums;
  }
  dl {
    display: grid;
    grid-template-columns: 1fr auto;
    gap: 2px 12px;
    margin: 8px 0 0;
    font-size: 0.85rem;
  }
  dt {
    color: var(--muted);
  }
  dd {
    margin: 0;
    text-align: right;
    font-variant-numeric: tabular-nums;
  }
  .dot {
    display: inline-block;
    width: 10px;
    height: 10px;
    border-radius: 3px;
    margin-right: 6px;
    vertical-align: -1px;
  }
  .split {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(min(340px, 100%), 1fr));
    gap: 16px;
  }
  .split > section {
    align-content: start;
  }
  .list {
    list-style: none;
    margin: 0;
    padding: 0;
  }
  .list li {
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
  .val {
    display: grid;
    justify-items: end;
  }
  a {
    color: inherit;
  }
  .legend {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-wrap: wrap;
    gap: 6px 16px;
  }
</style>
