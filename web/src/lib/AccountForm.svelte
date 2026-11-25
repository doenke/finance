<script lang="ts">
  import { goto } from '$app/navigation';
  import { onMount, untrack } from 'svelte';
  import { api, type Account } from './api.ts';
  import DecimalInput from './DecimalInput.svelte';
  import { loadMeta, meta } from './meta.svelte.ts';
  import { household, loadPersons } from './persons.svelte.ts';
  import { session } from './session.svelte.ts';

  let { account = null }: { account?: Account | null } = $props();

  interface Planned {
    date: string;
    amount: string;
    repeat: boolean;
    until: string;
  }

  // The form edits a snapshot of the account passed in.
  const init = untrack(() => account);
  let name = $state(init?.name ?? '');
  let kind = $state(init?.kind ?? 'giro');
  let institution = $state(init?.institution ?? '');
  let iban = $state(init?.iban ?? '');
  let openedOn = $state(init?.opened_on ?? '');
  let notes = $state(init?.notes ?? '');
  let closed = $state(init?.closed ?? false);
  let settlementId = $state<number | null>(init?.settlement_account_id ?? null);
  let details = $state<Record<string, any>>({ liquidity: '', ...(init?.details ?? {}) });
  let planned = $state<Planned[]>(
    (init?.details?.planned_prepayments ?? []).map((p: any) => ({ date: p.date, amount: String(p.amount), repeat: p.repeat === 'yearly', until: p.until ?? '' }))
  );
  let installmentChanges = $state<{ date: string; installment: string }[]>(
    (init?.details?.installment_changes ?? []).map((c: any) => ({ date: c.date, installment: String(c.installment) }))
  );
  let ownerShares = $state<Record<number, string>>({});
  let others = $state<Account[]>([]);
  let error = $state('');
  let saving = $state(false);

  onMount(async () => {
    await Promise.all([loadMeta(), loadPersons()]);
    others = (await api.get<Account[]>('/api/accounts')).filter((a) => a.id !== init?.id);
    if (init) {
      for (const o of init.owners) ownerShares[o.person_id] = String(Math.round(Number(o.share) * 10000) / 100);
    } else if (session.me?.person_id) {
      ownerShares[session.me.person_id] = '100';
    }
  });

  const kindMeta = $derived(meta.value?.kinds.find((k) => k.key === kind));
  const mode = $derived(kindMeta?.mode ?? 'cash');
  const isBound = $derived(details.liquidity === 'bound' || (!details.liquidity && !!kindMeta?.bound));
  const cashAccounts = $derived(others.filter((a) => a.mode === 'cash' && !a.closed));
  const properties = $derived(others.filter((a) => a.kind === 'immobilie'));
  const persons = $derived(household.persons.filter((p) => !p.archived || ownerShares[p.id] !== undefined));
  const kindLocked = $derived(init !== null);
  const sameModeKinds = $derived(meta.value?.kinds.filter((k) => !kindLocked || k.mode === mode) ?? []);

  function toggleOwner(id: number, checked: boolean) {
    if (checked) ownerShares[id] = '0';
    else delete ownerShares[id];
    const ids = Object.keys(ownerShares);
    const even = Math.floor((10000 / ids.length)) / 100;
    ids.forEach((pid, i) => (ownerShares[Number(pid)] = String(i === 0 ? Math.round((100 - even * (ids.length - 1)) * 100) / 100 : even)));
  }

  function addPlanned() {
    planned.push({ date: '', amount: '', repeat: true, until: '' });
  }

  async function submit(event: SubmitEvent) {
    event.preventDefault();
    error = '';
    const owners = Object.entries(ownerShares).map(([pid, pctValue]) => ({ person_id: Number(pid), share: (Number(String(pctValue).replace(',', '.')) / 100).toFixed(6) }));
    const total = owners.reduce((s, o) => s + Number(o.share), 0);
    if (!owners.length || Math.abs(total - 1) > 0.0001) {
      error = 'Die Anteile der Eigentümer müssen zusammen 100 % ergeben.';
      return;
    }
    const cleanDetails: Record<string, any> = {};
    for (const [k, v] of Object.entries(details)) if (v !== '' && v !== null && v !== undefined) cleanDetails[k] = v;
    if (mode === 'loan') {
      cleanDetails.planned_prepayments = planned
        .filter((p) => p.date && p.amount)
        .map((p) => ({ date: p.date, amount: p.amount, repeat: p.repeat ? 'yearly' : null, until: p.until || null }));
      cleanDetails.installment_changes = installmentChanges
        .filter((c) => c.date && c.installment)
        .sort((a, b) => a.date.localeCompare(b.date))
        .map((c) => ({ date: c.date, installment: c.installment }));
    }
    const body = {
      name,
      kind,
      institution,
      iban: mode === 'cash' ? iban : '',
      opened_on: openedOn || null,
      closed,
      notes,
      details: cleanDetails,
      settlement_account_id: mode === 'holdings' ? settlementId : null,
      owners
    };
    saving = true;
    try {
      const saved = init ? await api.put<Account>(`/api/accounts/${init.id}`, body) : await api.post<Account>('/api/accounts', body);
      await goto(`/konten/${saved.id}`);
    } catch (e) {
      error = (e as Error).message;
    } finally {
      saving = false;
    }
  }
</script>

<form class="stack" onsubmit={submit}>
  <section class="card stack">
    <div class="grid">
      <label class="wide">Name <input bind:value={name} required maxlength="120" placeholder="z. B. Girokonto Sparkasse" /></label>
      <label>
        Art
        <select bind:value={kind}>
          {#each sameModeKinds as k (k.key)}<option value={k.key}>{k.label}</option>{/each}
        </select>
      </label>
      <label>Bank / Anbieter <input bind:value={institution} maxlength="120" /></label>
      {#if mode === 'cash'}
        <label>IBAN <input bind:value={iban} maxlength="42" autocomplete="off" /></label>
      {/if}
      <label>Eröffnet am <input type="date" bind:value={openedOn} /></label>
    </div>
  </section>

  {#if mode === 'deposit'}
    <section class="card stack">
      <h2>Festgeld</h2>
      <div class="grid">
        <label>Anlagebetrag <DecimalInput bind:value={details.amount} suffix="€" required /></label>
        <label>Zinssatz p. a. <DecimalInput bind:value={details.rate} suffix="%" required /></label>
        <label>Beginn <input type="date" bind:value={details.start} required /></label>
        <label>Fällig am <input type="date" bind:value={details.end} /></label>
      </div>
    </section>
  {:else if mode === 'loan'}
    <section class="card stack">
      <h2>Darlehen</h2>
      <div class="grid">
        <label>Darlehensbetrag <DecimalInput bind:value={details.principal} suffix="€" required /></label>
        <label>Ausgezahlt am <input type="date" bind:value={details.disbursed_on} required /></label>
        <label>Sollzins p. a. <DecimalInput bind:value={details.rate} suffix="%" required /></label>
        <label>
          Art
          <select bind:value={details.mode}>
            <option value="annuity">Annuitätendarlehen</option>
            <option value="fixed_repayment">Feste Tilgung</option>
          </select>
        </label>
        <label>Rate je Zahlung <DecimalInput bind:value={details.installment} suffix="€" placeholder="oder Tilgung angeben" /></label>
        <label>Anfängliche Tilgung p. a. <DecimalInput bind:value={details.initial_repayment} suffix="%" placeholder="z. B. 2" /></label>
        <label>
          Zahlungen
          <select bind:value={details.frequency}>
            <option value={12}>monatlich</option>
            <option value={4}>vierteljährlich</option>
          </select>
        </label>
        <label>Erste Rate am <input type="date" bind:value={details.first_payment} required /></label>
        <label>Zinsbindung bis <input type="date" bind:value={details.fixed_until} /></label>
        <label>Tilgungsfrei bis <input type="date" bind:value={details.grace_until} /></label>
        <label>Sondertilgung erlaubt p. a. <DecimalInput bind:value={details.prepayment_allowance_pct} suffix="%" placeholder="z. B. 5" /></label>
        <label>Angenommener Anschlusszins <DecimalInput bind:value={details.followup_rate} suffix="%" /></label>
        {#if properties.length}
          <label>
            Gehört zu Immobilie
            <select bind:value={details.property_id}>
              <option value={undefined}>–</option>
              {#each properties as p (p.id)}<option value={p.id}>{p.name}</option>{/each}
            </select>
          </label>
        {/if}
      </div>
      <h3>Ratenänderungen</h3>
      <p class="muted small">Hat sich die Rate geändert – oder wird sie sich ändern? Ab dem Datum gilt die neue Rate {details.mode === 'fixed_repayment' ? '(Tilgungsanteil)' : '(Zins + Tilgung)'}.</p>
      {#each installmentChanges as c, i (i)}
        <div class="planned">
          <label>Ab <input type="date" bind:value={c.date} /></label>
          <label>Neue Rate <DecimalInput bind:value={c.installment} suffix="€" /></label>
          <button type="button" class="btn danger" onclick={() => installmentChanges.splice(i, 1)}>Entfernen</button>
        </div>
      {/each}
      <div><button type="button" class="btn" onclick={() => installmentChanges.push({ date: '', installment: '' })}>+ Ratenänderung</button></div>

      <h3>Geplante Sondertilgungen</h3>
      {#each planned as p, i (i)}
        <div class="planned">
          <label>Datum <input type="date" bind:value={p.date} /></label>
          <label>Betrag <DecimalInput bind:value={p.amount} suffix="€" /></label>
          <label class="check"><input type="checkbox" bind:checked={p.repeat} /> jährlich</label>
          {#if p.repeat}<label>bis <input type="date" bind:value={p.until} /></label>{/if}
          <button type="button" class="btn danger" onclick={() => planned.splice(i, 1)}>Entfernen</button>
        </div>
      {/each}
      <div><button type="button" class="btn" onclick={addPlanned}>+ Geplante Sondertilgung</button></div>
    </section>
  {:else if kind === 'immobilie'}
    <section class="card stack">
      <h2>Immobilie</h2>
      <div class="grid">
        <label>Kaufpreis <DecimalInput bind:value={details.purchase_price} suffix="€" /></label>
        <label>Kaufnebenkosten <DecimalInput bind:value={details.purchase_costs} suffix="€" /></label>
        <label>Gekauft am <input type="date" bind:value={details.purchase_date} /></label>
        <label>
          Nutzung
          <select bind:value={details.usage}>
            <option value="self">selbstgenutzt</option>
            <option value="rented">vermietet</option>
          </select>
        </label>
      </div>
    </section>
  {:else if kind === 'altersvorsorge'}
    <section class="card stack">
      <h2>Vertrag</h2>
      <div class="grid">
        <label>
          Produkt
          <select bind:value={details.product}>
            <option value="gesetzlich">Gesetzliche Rente (DRV)</option>
            <option value="riester">Riester</option>
            <option value="ruerup">Rürup / Basisrente</option>
            <option value="bav">Betriebliche Altersvorsorge</option>
            <option value="rente">Private Rentenversicherung</option>
            <option value="leben">Lebensversicherung</option>
            <option value="bauspar">Bausparvertrag</option>
            <option value="other">Sonstiges</option>
          </select>
        </label>
        <label>Vertragsnummer <input bind:value={details.contract_no} /></label>
        <label>Prognostizierte Rente / Monat <DecimalInput bind:value={details.expected_pension} suffix="€" /></label>
        <label>Rentenbeginn <input type="date" bind:value={details.payout_start} /></label>
        {#if details.product === 'gesetzlich'}
          <label>Bisher erreichte Rente / Monat <DecimalInput bind:value={details.current_pension} suffix="€" /></label>
          <label>Stand der Renteninformation <input type="date" bind:value={details.info_date} /></label>
        {/if}
      </div>
    </section>
  {:else if mode === 'holdings'}
    <section class="card stack">
      <h2>Verrechnungskonto</h2>
      <label>
        Konto für Ein- und Auszahlungen (optional)
        <select bind:value={settlementId}>
          <option value={null}>–</option>
          {#each cashAccounts as a (a.id)}<option value={a.id}>{a.name}</option>{/each}
        </select>
      </label>
    </section>
  {/if}

  <section class="card stack">
    <h2>Wem gehört es?</h2>
    <div class="owners">
      {#each persons as p (p.id)}
        <div class="owner">
          <label class="check"><input type="checkbox" checked={ownerShares[p.id] !== undefined} onchange={(e) => toggleOwner(p.id, e.currentTarget.checked)} /> {p.name}</label>
          {#if ownerShares[p.id] !== undefined && Object.keys(ownerShares).length > 1}
            <span class="share"><input type="text" inputmode="decimal" bind:value={ownerShares[p.id]} aria-label="Anteil {p.name} in Prozent" /> %</span>
          {/if}
        </div>
      {/each}
    </div>
  </section>

  <section class="card stack">
    {#if kindMeta && !kindMeta.liability}
      <div class="liq">
        <label>
          Verfügbarkeit
          <select bind:value={details.liquidity}>
            <option value="">automatisch ({kindMeta.bound ? 'gebunden' : 'verfügbar'})</option>
            <option value="available">verfügbar – kurzfristig nutzbar</option>
            <option value="bound">gebunden – festgelegt</option>
          </select>
        </label>
        {#if isBound && kind !== 'festgeld' && kind !== 'altersvorsorge'}
          <label>Frei ab (optional) <input type="date" bind:value={details.free_from} /></label>
        {/if}
      </div>
    {/if}
    <label>Notizen <textarea rows="3" bind:value={notes}></textarea></label>
    {#if init}
      <label class="check"><input type="checkbox" bind:checked={closed} /> Aufgelöst (zählt nicht mehr zum aktuellen Vermögen)</label>
    {/if}
  </section>

  {#if error}<p class="error">{error}</p>{/if}
  <div class="row">
    <button class="btn primary" type="submit" disabled={saving}>Speichern</button>
    <a class="btn" href={init ? `/konten/${init.id}` : '/konten'}>Abbrechen</a>
  </div>
</form>

<style>
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
    gap: 12px;
  }
  .wide {
    grid-column: 1 / -1;
  }
  textarea {
    padding: 8px 12px;
  }
  .check {
    display: flex;
    flex-direction: row;
    align-items: center;
    gap: 8px;
    color: var(--text);
  }
  .check input {
    width: auto;
    min-height: auto;
  }
  .owners {
    display: grid;
    gap: 8px;
  }
  .owner {
    display: flex;
    align-items: center;
    gap: 12px;
    min-height: 40px;
  }
  .share {
    display: inline-flex;
    align-items: center;
    gap: 6px;
  }
  .share input {
    width: 80px;
    text-align: right;
  }
  .planned {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
    gap: 8px;
    align-items: end;
    padding-bottom: 8px;
    border-bottom: 1px dashed var(--border);
  }
  h3 {
    font-size: 1rem;
    margin: 8px 0 0;
  }
  .small {
    font-size: 0.85rem;
    margin: 0;
  }
  .liq {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
    gap: 12px;
  }
</style>
