<script lang="ts">
  import PrivacyToggle from '#lib/PrivacyToggle.svelte';
  import { onMount } from 'svelte';
  import { api, type Account, type NetWorthData } from '#lib/api.ts';
  import BarList from '#lib/charts/BarList.svelte';
  import LineChart from '#lib/charts/LineChart.svelte';
  import { formatMoney, toNumber } from '#lib/format.ts';
  import { label, loadMeta, meta } from '#lib/meta.svelte.ts';
  import Money from '#lib/Money.svelte';
  import PerformanceCard from '#lib/PerformanceCard.svelte';
  import ReturnBreakdown from '#lib/ReturnBreakdown.svelte';
  import LiquidityCard from '#lib/LiquidityCard.svelte';
  import PeriodPicker from '#lib/PeriodPicker.svelte';
  import PersonFilter from '#lib/PersonFilter.svelte';
  import { household, loadPersons } from '#lib/persons.svelte.ts';
  import { session } from '#lib/session.svelte.ts';

  let period = $state('1Y');
  let nw = $state<NetWorthData | null>(null);
  let accounts = $state<Account[]>([]);
  let ready = $state(false);
  let error = $state('');

  const greeting = (() => {
    const h = new Date().getHours();
    if (h < 11) return 'Guten Morgen';
    if (h < 18) return 'Hallo';
    return 'Guten Abend';
  })();
  const firstName = $derived(session.me?.name.split(' ')[0] ?? '');

  onMount(async () => {
    try {
      await Promise.all([loadMeta(), loadPersons()]);
      accounts = await api.get<Account[]>('/api/accounts');
    } catch (e) {
      error = (e as Error).message;
    } finally {
      ready = true;
    }
  });

  $effect(() => {
    const p = period;
    const person = household.filter;
    api
      .get<NetWorthData>(`/api/networth?period=${p}${person !== null ? `&person_id=${person}` : ''}`)
      .then((d) => (nw = d))
      .catch((e) => (error = (e as Error).message));
  });

  const eur = (v: number) => formatMoney(v, 'EUR', false);
  const netSeries = $derived(
    nw ? [{ key: 'net', label: 'Nettovermögen', color: 'var(--series-1)', points: nw.series.map((p) => ({ date: p.date, value: toNumber(p.net) })) }] : []
  );
  const classItems = $derived(
    Object.entries(nw?.current?.by_class ?? {})
      .filter(([k, v]) => k !== 'liabilities' && toNumber(v) > 0)
      .map(([k, v]) => ({ key: k, label: label(meta.value?.asset_classes, k), value: toNumber(v) }))
      .sort((a, b) => b.value - a.value)
  );
  const personItems = $derived(
    household.persons
      .filter((p) => !p.archived)
      .map((p) => ({
        key: String(p.id),
        label: p.name,
        color: p.color,
        value: accounts.filter((a) => !a.closed).reduce((s, a) => s + toNumber(a.value) * toNumber(a.owners.find((o) => o.person_id === p.id)?.share ?? 0), 0)
      }))
      .filter((p) => p.value !== 0)
  );
  const change = (v: string | null | undefined) => (v === null || v === undefined ? null : toNumber(v));
</script>

<svelte:head><title>Übersicht – Finanzen</title></svelte:head>

<div class="stack">
  <div class="title">
    <h1>{greeting}, {firstName}</h1>
    <PrivacyToggle />
  </div>
  <PersonFilter />
  {#if error}<p class="error">{error}</p>{/if}

  {#if ready && accounts.length === 0}
    <div class="card stack empty">
      <h2>Willkommen bei Finanzen</h2>
      <p class="muted">Leg unter <a href="/konten">Konten</a> euer erstes Konto an – das Girokonto, das Depot, die Wohnung oder den Kredit. Sobald Daten da sind, siehst du hier euer Nettovermögen, die Aufteilung und eure Rendite.</p>
      <a class="btn primary" href="/konten/neu">Erstes Konto anlegen</a>
    </div>
  {:else if nw?.current}
    {@const c = nw.current}
    <section class="hero card">
      <div class="main">
        <span class="muted">Nettovermögen</span>
        <strong class="big"><Money value={c.net} cents={false} /></strong>
      </div>
      <div><span class="muted">Vermögen</span><strong><Money value={c.assets} cents={false} /></strong></div>
      <div><span class="muted">Schulden</span><strong><Money value={c.liabilities} cents={false} /></strong></div>
      <div>
        <span class="muted">seit Vormonat</span>
        <strong>{#if change(c.change_month) !== null}<Money value={change(c.change_month)} cents={false} colored />{:else}–{/if}</strong>
      </div>
      <div>
        <span class="muted">seit Jahresbeginn</span>
        <strong>{#if change(c.change_ytd) !== null}<Money value={change(c.change_ytd)} cents={false} colored />{:else}–{/if}</strong>
      </div>
    </section>

    <LiquidityCard personId={household.filter} />

    <section class="card stack">
      <div class="row head">
        <h2>Nettovermögen im Verlauf</h2>
        <PeriodPicker bind:value={period} />
      </div>
      {#if nw.series.length > 1}
        <LineChart series={netSeries} format={eur} money area ariaLabel="Nettovermögen im Verlauf" />
      {:else}
        <p class="muted">Für einen Verlauf braucht es Werte an mehreren Tagen.</p>
      {/if}
    </section>

    <div class="split">
      <section class="card stack">
        <h2>Nach Anlageklasse</h2>
        <BarList items={classItems} format={eur} money />
        {#if toNumber(c.liabilities) < 0}<p class="muted small">Dazu kommen Schulden von <span class="money">{eur(toNumber(c.liabilities))}</span>.</p>{/if}
      </section>
      {#if personItems.length > 1 && household.filter === null}
        <section class="card stack">
          <h2>Nach Person</h2>
          <BarList items={personItems} format={eur} money />
          <p class="muted small">Gemeinsame Konten zählen mit dem jeweiligen Anteil; netto nach Schulden.</p>
        </section>
      {/if}
    </div>

    <PerformanceCard title="Rendite eurer Anlagen" params={{ person_id: household.filter }} />
    <ReturnBreakdown personId={household.filter} />
  {:else if !error}
    <p class="muted">Lädt …</p>
  {/if}
</div>

<style>
  .title {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
  }
  .title h1 {
    margin: 0;
  }
  .hero {
    display: grid;
    grid-template-columns: 1.6fr repeat(4, 1fr);
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
    font-size: 2rem;
    line-height: 1.1;
  }
  .head {
    justify-content: space-between;
  }
  .head h2 {
    margin: 0;
  }
  .split {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(min(300px, 100%), 1fr));
    gap: 16px;
  }
  .small {
    font-size: 0.85rem;
    margin: 0;
  }
  .empty {
    justify-items: start;
  }
  @media (max-width: 760px) {
    .hero {
      grid-template-columns: 1fr 1fr;
    }
    .hero .main {
      grid-column: 1 / -1;
    }
  }
</style>
