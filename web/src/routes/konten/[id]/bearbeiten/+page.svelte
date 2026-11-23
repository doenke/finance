<script lang="ts">
  import { page } from '$app/state';
  import { onMount } from 'svelte';
  import AccountForm from '#lib/AccountForm.svelte';
  import { api, type Account } from '#lib/api.ts';

  let account = $state<Account | null>(null);
  let error = $state('');
  onMount(async () => {
    try {
      account = await api.get<Account>(`/api/accounts/${page.params.id}`);
    } catch (e) {
      error = (e as Error).message;
    }
  });
</script>

<svelte:head><title>Konto bearbeiten – Finanzen</title></svelte:head>

<div class="stack">
  <h1>Konto bearbeiten</h1>
  {#if error}<p class="error">{error}</p>{/if}
  {#if account}<AccountForm {account} />{/if}
</div>
