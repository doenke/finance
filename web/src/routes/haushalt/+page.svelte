<script lang="ts">
  import { onMount } from 'svelte';
  import { api, type Person } from '#lib/api.ts';
  import Avatar from '#lib/Avatar.svelte';
  import Icon from '#lib/Icon.svelte';

  let persons = $state<Person[]>([]);
  let error = $state('');
  let editing = $state<{ id: number | null; name: string; color: string; archived: boolean } | null>(null);
  let saving = $state(false);

  async function load() {
    try {
      persons = await api.get<Person[]>('/api/persons');
    } catch (e) {
      error = (e as Error).message;
    }
  }

  function startNew() {
    editing = { id: null, name: '', color: '#2563eb', archived: false };
  }

  function startEdit(p: Person) {
    editing = { id: p.id, name: p.name, color: p.color, archived: p.archived };
  }

  async function save(event: SubmitEvent) {
    event.preventDefault();
    if (!editing) return;
    saving = true;
    error = '';
    try {
      const body = { name: editing.name, color: editing.color, archived: editing.archived };
      if (editing.id === null) await api.post('/api/persons', body);
      else await api.put(`/api/persons/${editing.id}`, body);
      editing = null;
      await load();
    } catch (e) {
      error = (e as Error).message;
    } finally {
      saving = false;
    }
  }

  async function remove(p: Person) {
    if (!confirm(`${p.name} wirklich entfernen?`)) return;
    try {
      await api.del(`/api/persons/${p.id}`);
      await load();
    } catch (e) {
      error = (e as Error).message;
    }
  }

  onMount(load);
</script>

<svelte:head><title>Haushalt – Finanzen</title></svelte:head>

<div class="stack">
  <div class="row head">
    <h1>Haushalt</h1>
    <button class="btn primary" onclick={startNew}><Icon name="plus" size={18} /> Person</button>
  </div>
  <p class="muted">
    Wer sich anmeldet, steht automatisch hier. Personen ohne Login – zum Beispiel Kinder – kannst du selbst anlegen, um ihnen später Konten
    und Anlagen zuzuordnen.
  </p>
  {#if error}<p class="error">{error}</p>{/if}

  {#if editing}
    <form class="card stack" onsubmit={save}>
      <h2>{editing.id === null ? 'Neue Person' : 'Person bearbeiten'}</h2>
      <div class="row">
        <label class="grow">Name <input bind:value={editing.name} required maxlength="100" /></label>
        <label>Farbe <input type="color" bind:value={editing.color} /></label>
      </div>
      {#if editing.id !== null}
        <label class="check"><input type="checkbox" bind:checked={editing.archived} /> Archiviert (nicht mehr im Haushalt)</label>
      {/if}
      <div class="row">
        <button class="btn primary" type="submit" disabled={saving}>Speichern</button>
        <button class="btn" type="button" onclick={() => (editing = null)}>Abbrechen</button>
      </div>
    </form>
  {/if}

  <ul class="list card">
    {#each persons as p (p.id)}
      <li class:archived={p.archived}>
        <Avatar name={p.name} url={p.avatar_url} color={p.color} size={40} />
        <div class="grow">
          <strong>{p.name}</strong>
          <div class="muted small">{p.user_id ? 'mit Login' : 'ohne Login'}{p.archived ? ' · archiviert' : ''}</div>
        </div>
        <button class="btn icon" title="Bearbeiten" aria-label="{p.name} bearbeiten" onclick={() => startEdit(p)}><Icon name="edit" size={18} /></button>
        {#if !p.user_id}
          <button class="btn icon danger" title="Entfernen" aria-label="{p.name} entfernen" onclick={() => remove(p)}><Icon name="trash" size={18} /></button>
        {/if}
      </li>
    {/each}
  </ul>
</div>

<style>
  .head {
    justify-content: space-between;
  }
  .head h1 {
    margin: 0;
  }
  .grow {
    flex: 1;
    min-width: 0;
  }
  .list {
    list-style: none;
    margin: 0;
    padding: 0;
  }
  .list li {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 12px 16px;
  }
  .list li + li {
    border-top: 1px solid var(--border);
  }
  .archived {
    opacity: 0.6;
  }
  .small {
    font-size: 0.85rem;
  }
  .btn.icon {
    padding: 0;
    width: 40px;
  }
  .check {
    display: flex;
    align-items: center;
    gap: 8px;
    color: var(--text);
  }
  .check input {
    width: auto;
    min-height: auto;
  }
</style>
