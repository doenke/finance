<script lang="ts">
  import { goto } from '$app/navigation';
  import { page } from '$app/state';
  import { api, type Account } from '#lib/api.ts';
  import DatedValuesPanel from '#lib/DatedValuesPanel.svelte';
  import { formatDate, formatPercent, toNumber } from '#lib/format.ts';
  import HoldingsPanel from '#lib/HoldingsPanel.svelte';
  import Icon from '#lib/Icon.svelte';
  import LoanPanel from '#lib/LoanPanel.svelte';
  import LoanScenarios from '#lib/LoanScenarios.svelte';
  import { label, loadMeta, meta } from '#lib/meta.svelte.ts';
  import Money from '#lib/Money.svelte';
  import PerformanceCard from '#lib/PerformanceCard.svelte';
  import FintsDialog from '#lib/FintsDialog.svelte';
  import type { BankLogin } from '#lib/api.ts';
  import { loadPersons, personName } from '#lib/persons.svelte.ts';
  import TransactionsPanel from '#lib/TransactionsPanel.svelte';

  let account = $state<Account | null>(null);
  let error = $state('');
  let refresh = $state(0);
  let bank = $state<BankLogin | null>(null);
  let syncing = $state(false);

  async function load() {
    try {
      await Promise.all([loadMeta(), loadPersons()]);
      const loaded = await api.get<Account>(`/api/accounts/${page.params.id}`);
      account = loaded;
      bank = loaded.bank_login_id ? ((await api.get<BankLogin[]>('/api/bank-logins')).find((b) => b.id === loaded.bank_login_id) ?? null) : null;
      refresh++;
    } catch (e) {
      error = (e as Error).message;
    }
  }

  $effect(() => {
    void page.params.id;
    load();
  });

  async function remove() {
    if (!account || !confirm(`„${account.name}“ mit allen Buchungen löschen? Das lässt sich nicht rückgängig machen.`)) return;
    await api.del(`/api/accounts/${account.id}`);
    goto('/konten');
  }

  async function reconcile() {
    if (!account) return;
    await api.post(`/api/accounts/${account.id}/reconcile`);
    await load();
  }

  async function unlink() {
    if (!account || !confirm('Verknüpfung mit dem Bankzugang lösen? Bisherige Daten bleiben erhalten.')) return;
    await api.post(`/api/accounts/${account.id}/unlink`);
    await load();
  }

  const owners = $derived(account?.owners.map((o) => `${personName(o.person_id)}${account!.owners.length > 1 ? ` ${Math.round(toNumber(o.share) * 100)} %` : ''}`).join(', ') ?? '');
</script>

<svelte:head><title>{account?.name ?? 'Konto'} – Finanzen</title></svelte:head>

{#if error}
  <p class="error">{error}</p>
{:else if account}
  <div class="stack">
    <a class="back" href="/konten">← Konten</a>
    <header class="card head">
      <div class="grow">
        <h1>{account.name}</h1>
        <div class="muted">
          {account.kind_label}{account.institution ? ` · ${account.institution}` : ''} · {owners}
          {#if account.closed}· aufgelöst{/if}
        </div>
        {#if account.iban}<div class="muted small num">{account.iban.replace(/(.{4})/g, '$1 ').trim()}</div>{/if}
      </div>
      <div class="value">
        <strong><Money value={account.value} /></strong>
        {#if account.value_as_of}<div class="muted small">Stand {formatDate(account.value_as_of)}</div>{/if}
      </div>
      <div class="actions">
        <a class="btn" href="/konten/{account.id}/bearbeiten"><Icon name="edit" size={18} /> Bearbeiten</a>
        <button class="btn danger" onclick={remove}><Icon name="trash" size={18} /> Löschen</button>
      </div>
    </header>

    {#if bank}
      <section class="card bankbar">
        <div class="grow">
          <strong>Verbunden mit {bank.name}{bank.mine ? '' : ` · Zugang von ${bank.owner || 'jemand anderem'}`}</strong>
          <div class="muted small">{bank.last_sync_at ? `Zuletzt abgerufen ${formatDate(bank.last_sync_at.slice(0, 10))}` : 'Noch nicht abgerufen'}{bank.needs_tan ? ' · TAN-Freigabe nötig' : ''}</div>
        </div>
        {#if bank.mine}<button class="btn primary" onclick={() => (syncing = true)}>Jetzt abrufen</button>{/if}
        <button class="btn" onclick={unlink}>Verknüpfung lösen</button>
      </section>
    {/if}
    {#if account.details.fints_differences?.length}
      <section class="card stack warnbox">
        <h2>Abweichung zum Bankbestand</h2>
        <ul class="small">
          {#each account.details.fints_differences as d (d.instrument_id)}
            <li>{d.name}: laut Bank {d.bank}, bei Finanzen {d.ours}</li>
          {/each}
        </ul>
        <p class="muted small">Meist fehlen noch Käufe oder Verkäufe. Trag sie als Transaktion nach – oder gleich die Differenz als Ein-/Auslieferung zum aktuellen Kurs buchen.</p>
        <div><button class="btn" onclick={reconcile}>Differenz buchen</button></div>
      </section>
    {/if}

    {#if account.mode !== 'loan' && !account.liability}
      {#key refresh}
        <PerformanceCard title="Wertentwicklung" params={{ account_id: account.id }} />
      {/key}
    {/if}

    {#if account.mode === 'cash'}
      <DatedValuesPanel
        accountId={account.id}
        endpoint="balances"
        field="amount"
        title="Kontostände"
        hint="Ein Kontostand zu einem Stichtag reicht – spätere Umsätze werden darauf gerechnet."
        onchange={load}
      />
      <TransactionsPanel accountId={account.id} onchange={load} />
    {:else if account.mode === 'holdings'}
      <HoldingsPanel accountId={account.id} accountKind={account.kind} onchange={load} />
    {:else if account.mode === 'valuation'}
      {#if account.kind === 'immobilie' && account.details.purchase_price}
        <section class="card facts">
          <div><span class="muted">Kaufpreis</span><strong><Money value={account.details.purchase_price} /></strong></div>
          {#if account.details.purchase_costs}<div><span class="muted">Nebenkosten</span><strong><Money value={account.details.purchase_costs} /></strong></div>{/if}
          {#if account.details.purchase_date}<div><span class="muted">Gekauft</span><strong>{formatDate(account.details.purchase_date)}</strong></div>{/if}
          <div>
            <span class="muted">Wertänderung</span>
            <strong><Money value={toNumber(account.value) - toNumber(account.details.purchase_price) - toNumber(account.details.purchase_costs)} colored /></strong>
          </div>
        </section>
      {/if}
      {#if account.kind === 'altersvorsorge' && (account.details.product || account.details.expected_pension)}
        <section class="card facts">
          {#if account.details.product}<div><span class="muted">Produkt</span><strong>{account.details.product}</strong></div>{/if}
          {#if account.details.expected_pension}<div><span class="muted">Prognose Rente / Monat</span><strong><Money value={account.details.expected_pension} /></strong></div>{/if}
          {#if account.details.payout_start}<div><span class="muted">Rentenbeginn</span><strong>{formatDate(account.details.payout_start)}</strong></div>{/if}
        </section>
      {/if}
      <DatedValuesPanel accountId={account.id} endpoint="valuations" field="value" title="Bewertungen" hint="Zum Beispiel Schätzwert der Wohnung oder Wert aus der jährlichen Standmitteilung." onchange={load} />
      <TransactionsPanel
        accountId={account.id}
        title={account.kind === 'immobilie' ? 'Einnahmen & Ausgaben' : 'Beiträge & Auszahlungen'}
        kinds={['contribution', 'deposit', 'withdrawal', 'income', 'fee', 'tax', 'other']}
        onchange={load}
      />
    {:else if account.mode === 'deposit'}
      <section class="card facts">
        <div><span class="muted">Anlagebetrag</span><strong><Money value={account.details.amount} /></strong></div>
        <div><span class="muted">Zinssatz</span><strong>{formatPercent(account.details.rate, false)}</strong></div>
        <div><span class="muted">Beginn</span><strong>{formatDate(account.details.start)}</strong></div>
        <div><span class="muted">Fällig</span><strong>{formatDate(account.details.end)}</strong></div>
      </section>
    {:else if account.mode === 'loan'}
      <LoanPanel {account} {refresh} />
      {#if account.details.principal && account.details.first_payment}
        {#key account.id}<LoanScenarios {account} />{/key}
      {/if}
      <DatedValuesPanel
        accountId={account.id}
        endpoint="balances"
        field="amount"
        title="Restschuld laut Bank"
        hint="Trag hier den Stand aus dem Kontoauszug ein – der Tilgungsplan rechnet dann ab diesem Wert weiter."
        negate
        onchange={load}
      />
      <TransactionsPanel accountId={account.id} title="Geleistete Sondertilgungen" fixedKind="prepayment" positiveOnly onchange={load} />
    {/if}

    {#if account.notes}
      <section class="card"><h2>Notizen</h2><p class="notes">{account.notes}</p></section>
    {/if}
    <p class="muted small">Anlageklasse: {label(meta.value?.asset_classes, account.asset_class)}</p>
  </div>
{/if}

{#if syncing && bank && account}
  <FintsDialog
    login={bank}
    kind="sync"
    accountIds={[account.id]}
    onclose={() => {
      syncing = false;
      load();
    }}
  />
{/if}

<style>
  .bankbar {
    display: flex;
    gap: 12px;
    align-items: center;
    flex-wrap: wrap;
  }
  .grow {
    flex: 1;
    min-width: 0;
  }
  .warnbox {
    border-color: var(--warn);
  }
  .warnbox ul {
    margin: 0;
    padding-left: 18px;
  }
  .back {
    text-decoration: none;
    font-size: 0.9rem;
  }
  .head {
    display: grid;
    grid-template-columns: 1fr auto;
    gap: 12px;
    align-items: start;
  }
  .head h1 {
    margin: 0 0 4px;
  }
  .grow {
    min-width: 0;
  }
  .value {
    text-align: right;
  }
  .value strong {
    font-size: 1.5rem;
  }
  .actions {
    grid-column: 1 / -1;
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
  }
  .small {
    font-size: 0.85rem;
  }
  .facts {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(170px, 1fr));
    gap: 12px;
  }
  .facts div {
    display: grid;
  }
  .facts span {
    font-size: 0.85rem;
  }
  .notes {
    white-space: pre-wrap;
    margin: 0;
  }
  @media (max-width: 520px) {
    .head {
      grid-template-columns: 1fr;
    }
    .value {
      text-align: left;
    }
  }
</style>
