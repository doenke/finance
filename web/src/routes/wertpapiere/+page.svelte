<script lang="ts">
  import { onMount } from 'svelte';
  import PersonFilter from '#lib/PersonFilter.svelte';
  import { household, loadPersons } from '#lib/persons.svelte.ts';
  import PositionCompare from '#lib/PositionCompare.svelte';

  onMount(loadPersons);
</script>

<svelte:head><title>Wertpapiere – Finanzen</title></svelte:head>

<div class="stack">
  <h1>Wertpapiere im Vergleich</h1>
  <p class="muted">Alle Positionen aus allen Depots, Krypto- und Edelmetallkonten zusammen – gleiche Wertpapiere in mehreren Depots werden addiert.</p>
  <PersonFilter />
  <PositionCompare personId={household.filter} title="Alle Positionen" />
</div>
