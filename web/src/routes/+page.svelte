<script lang="ts">
  import { session } from '#lib/session.svelte.ts';

  const greeting = (() => {
    const h = new Date().getHours();
    if (h < 11) return 'Guten Morgen';
    if (h < 18) return 'Hallo';
    return 'Guten Abend';
  })();
  const firstName = $derived(session.me?.name.split(' ')[0] ?? '');
</script>

<svelte:head><title>Übersicht – Finanzen</title></svelte:head>

<div class="stack">
  <h1>{greeting}, {firstName}</h1>
  <div class="card stack">
    <h2>Hier entsteht euer Finanzüberblick</h2>
    <p class="muted">
      Unter <a href="/konten">Konten</a> kannst du schon Girokonten, Depots, Immobilien, Kredite und alle anderen Anlagen anlegen. Als Nächstes
      kommen automatische Kurse, Rendite und das Dashboard mit eurem Nettovermögen.
    </p>
    <p class="muted">
      Schon jetzt kannst du unter <a href="/haushalt">Haushalt</a> festlegen, wer zum Haushalt gehört – auch Personen ohne eigenen Login,
      zum Beispiel Kinder.
    </p>
  </div>
</div>
