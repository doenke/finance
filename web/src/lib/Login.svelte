<script lang="ts">
  import { session } from './session.svelte';

  let devName = $state('');
  const returnTo = typeof location !== 'undefined' ? location.pathname + location.search : '/';
  const loginUrl = `/auth/login?return_to=${encodeURIComponent(returnTo)}`;
</script>

<div class="wrap">
  <div class="card stack login">
    <img src="/icon.svg" alt="" width="72" height="72" />
    <div>
      <h1>Finanzen</h1>
      <p class="muted">Euer Finanzüberblick – bitte melde dich an.</p>
    </div>
    {#if session.config?.oidc_enabled}
      <a class="btn primary" href={loginUrl}>Mit {session.config.provider_name} anmelden</a>
    {:else}
      <p class="error">Die Anmeldung ist noch nicht eingerichtet (OIDC_ISSUER und OIDC_CLIENT_ID in der .env).</p>
    {/if}
    {#if session.config?.dev_login}
      <form class="stack dev" method="GET" action="/auth/dev">
        <label>
          Entwickler-Login (nur zum Testen)
          <input name="name" bind:value={devName} placeholder="Name" required />
        </label>
        <button class="btn" type="submit">Ohne Anmeldedienst anmelden</button>
      </form>
    {/if}
    <p class="muted small">Version {session.config?.version}</p>
  </div>
</div>

<style>
  .wrap {
    min-height: 100dvh;
    display: grid;
    place-items: center;
    padding: 16px;
  }
  .login {
    width: 100%;
    max-width: 24rem;
    text-align: center;
    justify-items: center;
    padding: 32px 24px;
  }
  .login > * {
    width: 100%;
  }
  .login img {
    width: 72px;
  }
  .dev {
    border-top: 1px solid var(--border);
    padding-top: 16px;
    text-align: left;
  }
  .small {
    font-size: 0.85rem;
    margin: 0;
  }
</style>
