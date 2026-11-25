<script lang="ts">
  import PeriodPicker from '#lib/PeriodPicker.svelte';
  import PerformanceCard from '#lib/PerformanceCard.svelte';
  import PositionCompare from '#lib/PositionCompare.svelte';
  import ReturnBreakdown from '#lib/ReturnBreakdown.svelte';

  // one period for the whole page
  let period = $state('1Y');

</script>

<svelte:head><title>Anlagen – Finanzen</title></svelte:head>

<div class="stack">
  <div class="row head">
    <h1>Anlagen</h1>
    <PeriodPicker bind:value={period} />
  </div>
  <PerformanceCard title="Rendite eurer Anlagen" bind:period showPeriod={false} />
  <ReturnBreakdown bind:period showPeriod={false} />
  <PositionCompare title="Wertpapiere im Vergleich" bind:period showPeriod={false} />
</div>

<style>
  h1 {
    margin: 0;
  }
  .head {
    justify-content: space-between;
    flex-wrap: wrap;
    gap: 12px;
  }
</style>
