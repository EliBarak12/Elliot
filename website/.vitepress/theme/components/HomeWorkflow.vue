<script setup lang="ts">
import { onMounted, ref } from "vue";

const steps = [
  {
    title: "Connect your sources",
    body: "REST APIs, PostgreSQL, MySQL, CSV, JSON — all in one connector file.",
    code: "elliot init --template rest-api-key",
  },
  {
    title: "Build tools",
    body: "Declare name, description, parameters, filters, return fields. Elliot writes the safe, parameterized SQL.",
    code: "# define tools visually in Studio",
  },
  {
    title: "Lint for agent-readiness",
    body: "Every tool checked against the five principles before it ships.",
    code: "elliot lint my.connector.json",
  },
  {
    title: "Run eval cases",
    body: "Deterministic tool-call assertions with a token estimate — pass / fail per case, no LLM in the loop.",
    code: "elliot eval my.eval.yaml",
  },
  {
    title: "Deploy & connect",
    body: "Plugin + runtime + Studio come up with one command, ready for any MCP client.",
    code: "make dev",
  },
];

const el = ref<HTMLElement | null>(null);

onMounted(() => {
  if (!el.value || typeof IntersectionObserver === "undefined") return;
  const items = el.value.querySelectorAll<HTMLElement>(".elliot-reveal");
  const io = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry, i) => {
        if (entry.isIntersecting) {
          const elem = entry.target as HTMLElement;
          elem.style.transitionDelay = `${i * 60}ms`;
          elem.classList.add("is-visible");
          io.unobserve(elem);
        }
      });
    },
    { threshold: 0.12 },
  );
  items.forEach((item) => io.observe(item));
});
</script>

<template>
  <section ref="el" class="elliot-section">
    <span class="elliot-section__eyebrow">How it works</span>
    <h2 class="elliot-section__title">From your API to an agent-ready connector in five steps.</h2>
    <p class="elliot-section__lede">
      One connector file, one CLI, one running stack. No SQL writing, no glue
      services, no bespoke wrappers for every API your agent has to reach.
    </p>

    <div class="elliot-workflow">
      <article
        v-for="step in steps"
        :key="step.title"
        class="elliot-step elliot-reveal"
      >
        <div class="elliot-step__icon" aria-hidden="true">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M5 12l5 5L20 7" />
          </svg>
        </div>
        <h3 class="elliot-step__title">{{ step.title }}</h3>
        <p class="elliot-step__body">{{ step.body }}</p>
        <code class="elliot-step__code">{{ step.code }}</code>
      </article>
    </div>
  </section>
</template>
