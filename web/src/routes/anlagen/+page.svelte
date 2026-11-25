<script lang="ts">
  import PerformanceCard from '#lib/PerformanceCard.svelte';
  import PositionCompare from '#lib/PositionCompare.svelte';
  import ReturnBreakdown from '#lib/ReturnBreakdown.svelte';

</script>

<svelte:head><title>Anlagen – Finanzen</title></svelte:head>

<div class="stack">
  <h1>Anlagen</h1>
  <PerformanceCard title="Rendite eurer Anlagen" params={{}} />
  <ReturnBreakdown />
  <PositionCompare title="Wertpapiere im Vergleich" />
</div>

<style>
  h1 {
    margin: 0;
  }
</style>
