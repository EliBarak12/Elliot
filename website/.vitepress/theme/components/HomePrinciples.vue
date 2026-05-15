<script setup lang="ts">
import { onMounted, ref } from "vue";

const principles = [
  {
    title: "Tool descriptions are contracts",
    body: "Verb-first, unambiguous, typed. Agents pick the right tool every time — no guessing, no hallucinated parameters.",
  },
  {
    title: "Results fit the context window",
    body: "Pagination, projection, and aggregation by default. Agents see what they need, not raw 10MB JSON dumps.",
  },
  {
    title: "Errors are actionable",
    body: "Structured {code, message, details}. The agent knows whether to retry, narrow filters, or escalate to the user.",
  },
  {
    title: "Every session is observable",
    body: "Tokens, latency, errors, and tool args — all logged to NDJSON. Inspect any call in Studio, replay any session.",
  },
  {
    title: "The platform itself is agentic",
    body: "Agents build connectors through Elliot. discover-source → build → lint → eval → deploy, all callable as MCP tools.",
  },
];

const sectionEl = ref<HTMLElement | null>(null);

onMounted(() => {
  if (!sectionEl.value || typeof IntersectionObserver === "undefined") return;
  const items = sectionEl.value.querySelectorAll<HTMLElement>(".elliot-reveal");
  const io = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry, i) => {
        if (entry.isIntersecting) {
          const el = entry.target as HTMLElement;
          el.style.transitionDelay = `${i * 60}ms`;
          el.classList.add("is-visible");
          io.unobserve(el);
        }
      });
    },
    { threshold: 0.12 },
  );
  items.forEach((el) => io.observe(el));
});
</script>

<template>
  <section ref="sectionEl" class="elliot-section">
    <span class="elliot-section__eyebrow">The five principles</span>
    <h2 class="elliot-section__title">Designed for agents, not humans.</h2>
    <p class="elliot-section__lede">
      Every connector Elliot ships follows five rules. They are the
      difference between a connector an agent occasionally gets right and a
      connector it can reliably call in production.
    </p>

    <div class="elliot-principles">
      <article
        v-for="(p, i) in principles"
        :key="p.title"
        class="elliot-principle elliot-reveal"
      >
        <div class="elliot-principle__num">{{ String(i + 1).padStart(2, "0") }}</div>
        <h3 class="elliot-principle__title">{{ p.title }}</h3>
        <p class="elliot-principle__body">{{ p.body }}</p>
      </article>
    </div>
  </section>
</template>
