<script lang="ts">
  import PrivacyToggle from '#lib/PrivacyToggle.svelte';
  import { onMount } from 'svelte';
  import { api, type Account, type NetWorthData } from '#lib/api.ts';
  import LineChart from '#lib/charts/LineChart.svelte';
  import { formatMoney, toNumber } from '#lib/format.ts';
  import { loadMeta } from '#lib/meta.svelte.ts';
  import Money from '#lib/Money.svelte';
  import ReturnSummary from '#lib/ReturnSummary.svelte';
  import LiquidityCard from '#lib/LiquidityCard.svelte';
  import PeriodPicker from '#lib/PeriodPicker.svelte';
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
      await loadMeta();
      accounts = await api.get<Account[]>('/api/accounts');
    } catch (e) {
      error = (e as Error).message;
    } finally {
      ready = true;
    }
  });

  $effect(() => {
    const p = period;
    api
      .get<NetWorthData>(`/api/networth?period=${p}`)
      .then((d) => (nw = d))
      .catch((e) => (error = (e as Error).message));
  });

  const eur = (v: number) => formatMoney(v, 'EUR', false);
  const netSeries = $derived(
    nw ? [{ key: 'net', label: 'Nettovermögen', color: 'var(--series-1)', points: nw.series.map((p) => ({ date: p.date, value: toNumber(p.net) })) }] : []
  );
  const change = (v: string | null | undefined) => (v === null || v === undefined ? null : toNumber(v));
</script>

<svelte:head><title>Übersicht – Finanzen</title></svelte:head>

<div class="stack">
  <div class="title">
    <h1>{greeting}, {firstName}</h1>
    <PrivacyToggle />
  </div>
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

    <LiquidityCard />

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

    <ReturnSummary bind:period showPeriod={false} />
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
