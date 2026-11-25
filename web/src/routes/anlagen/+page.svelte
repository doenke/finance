<script lang="ts">
  import { onMount } from 'svelte';
  import PerformanceCard from '#lib/PerformanceCard.svelte';
  import PersonFilter from '#lib/PersonFilter.svelte';
  import { household, loadPersons } from '#lib/persons.svelte.ts';
  import PositionCompare from '#lib/PositionCompare.svelte';
  import ReturnBreakdown from '#lib/ReturnBreakdown.svelte';

  onMount(loadPersons);
</script>

<svelte:head><title>Anlagen – Finanzen</title></svelte:head>

<div class="stack">
  <h1>Anlagen</h1>
  <PersonFilter />
  <PerformanceCard title="Rendite eurer Anlagen" params={{ person_id: household.filter }} />
  <ReturnBreakdown personId={household.filter} />
  <PositionCompare personId={household.filter} title="Wertpapiere im Vergleich" />
</div>

<style>
  h1 {
    margin: 0;
  }
</style>
