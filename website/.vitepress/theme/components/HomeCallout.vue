<script setup lang="ts">
import { withBase } from "vitepress";
</script>

<template>
  <section class="elliot-section">
    <div class="elliot-cta">
      <h2 class="elliot-cta__title">Ready to make your product agentic?</h2>
      <p class="elliot-cta__body">
        Clone the repo, run <code>make dev</code>, and your first connector is
        live on an MCP endpoint in under five minutes. Free, MIT-licensed, and
        runs anywhere you can run Python and Node.
      </p>
      <div class="elliot-cta__buttons">
        <a class="elliot-cta__btn elliot-cta__btn--primary" :href="withBase('/docs/quickstart')">
          Start the quickstart
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M5 12h14" />
            <path d="M13 6l6 6-6 6" />
          </svg>
        </a>
        <a class="elliot-cta__btn elliot-cta__btn--ghost" href="https://github.com/EliBarak12/Elliot" target="_blank" rel="noopener">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
            <path d="M12 .5C5.4.5 0 5.9 0 12.5c0 5.3 3.4 9.8 8.2 11.4.6.1.8-.3.8-.6v-2c-3.3.7-4-1.6-4-1.6-.6-1.4-1.4-1.8-1.4-1.8-1.1-.8.1-.8.1-.8 1.2.1 1.9 1.3 1.9 1.3 1.1 1.9 2.9 1.3 3.6 1 .1-.8.4-1.3.8-1.6-2.7-.3-5.5-1.3-5.5-6 0-1.3.5-2.3 1.3-3.2-.1-.3-.5-1.6.1-3.3 0 0 1-.3 3.3 1.2A11 11 0 0 1 12 6c1 0 2.1.1 3.1.4 2.4-1.6 3.4-1.2 3.4-1.2.6 1.7.2 3 .1 3.3.8.9 1.3 1.9 1.3 3.2 0 4.7-2.9 5.7-5.5 6 .4.4.8 1.1.8 2.3v3.4c0 .3.2.7.8.6A12 12 0 0 0 24 12.5C24 5.9 18.6.5 12 .5z" />
          </svg>
          View on GitHub
        </a>
      </div>
    </div>
  </section>
</template>
