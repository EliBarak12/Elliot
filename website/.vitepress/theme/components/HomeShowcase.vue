<script setup lang="ts">
import { onMounted, ref } from "vue";
import { withBase } from "vitepress";

const shots = [
  { src: "/screenshots/studio-tools.png", label: "Tools — verb-first, typed contracts your agents call" },
  { src: "/screenshots/studio-metrics.png", label: "Metrics — calls, error rate, latency, token efficiency" },
  { src: "/screenshots/studio-agent-console.png", label: "Agent Console — a live trace of every session" },
  { src: "/screenshots/studio-sources.png", label: "Sources — REST, PostgreSQL, MySQL, and files" },
];

const el = ref<HTMLElement | null>(null);

onMounted(() => {
  if (!el.value || typeof IntersectionObserver === "undefined") return;
  const io = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry, i) => {
        if (entry.isIntersecting) {
          const node = entry.target as HTMLElement;
          node.style.transitionDelay = `${i * 70}ms`;
          node.classList.add("is-visible");
          io.unobserve(node);
        }
      });
    },
    { threshold: 0.12 },
  );
  el.value
    .querySelectorAll<HTMLElement>(".elliot-reveal")
    .forEach((item) => io.observe(item));
});
</script>

<template>
  <section ref="el" class="elliot-section">
    <span class="elliot-section__eyebrow">See it in action</span>
    <h2 class="elliot-section__title">Studio — a glass cockpit for every agent session.</h2>
    <p class="elliot-section__lede">
      Watch a connector come together: five data sources, typed tools, a
      built connector, and two agents calling it — every call traced, timed,
      and token-counted in real time.
    </p>

    <div class="elliot-showcase elliot-reveal">
      <div class="elliot-browser">
        <div class="elliot-browser__bar">
          <span class="elliot-browser__dot elliot-browser__dot--r"></span>
          <span class="elliot-browser__dot elliot-browser__dot--y"></span>
          <span class="elliot-browser__dot elliot-browser__dot--g"></span>
          <span class="elliot-browser__url">localhost — Elliot Studio</span>
        </div>
        <video
          class="elliot-browser__video"
          :src="withBase('/elliot-demo.webm')"
          :poster="withBase('/screenshots/studio-dashboard.png')"
          autoplay
          muted
          loop
          playsinline
          preload="metadata"
        ></video>
      </div>
    </div>

    <div class="elliot-shots">
      <figure
        v-for="shot in shots"
        :key="shot.src"
        class="elliot-shot elliot-reveal"
      >
        <img :src="withBase(shot.src)" :alt="shot.label" loading="lazy" />
        <figcaption class="elliot-shot__caption">{{ shot.label }}</figcaption>
      </figure>
    </div>
  </section>
</template>

<style scoped>
.elliot-showcase {
  margin-top: 2.6rem;
}

.elliot-browser {
  border: 1px solid var(--elliot-border);
  border-radius: 14px;
  overflow: hidden;
  background: var(--elliot-surface);
  box-shadow: var(--elliot-shadow-lg, var(--elliot-shadow-md));
}

.elliot-browser__bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 11px 16px;
  border-bottom: 1px solid var(--elliot-border);
  background: var(--elliot-surface-2);
}

.elliot-browser__dot {
  width: 11px;
  height: 11px;
  border-radius: 50%;
  display: inline-block;
}
.elliot-browser__dot--r { background: #ff5f57; }
.elliot-browser__dot--y { background: #febc2e; }
.elliot-browser__dot--g { background: #28c840; }

.elliot-browser__url {
  margin-left: 10px;
  font-family: var(--vp-font-family-mono);
  font-size: 0.76rem;
  color: var(--elliot-text-muted);
}

.elliot-browser__video {
  display: block;
  width: 100%;
  height: auto;
  background: var(--elliot-surface-2);
}

.elliot-shots {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 18px;
  margin-top: 22px;
}

@media (min-width: 860px) {
  .elliot-shots {
    grid-template-columns: repeat(4, 1fr);
  }
}

.elliot-shot {
  margin: 0;
  border: 1px solid var(--elliot-border);
  border-radius: 12px;
  overflow: hidden;
  background: var(--elliot-surface);
  transition:
    transform 0.25s ease,
    box-shadow 0.25s ease;
}

.elliot-shot:hover {
  transform: translateY(-3px);
  box-shadow: var(--elliot-shadow-md);
}

.elliot-shot img {
  display: block;
  width: 100%;
  height: 150px;
  object-fit: cover;
  object-position: top center;
  border-bottom: 1px solid var(--elliot-border);
}

.elliot-shot__caption {
  padding: 11px 14px;
  font-size: 0.78rem;
  line-height: 1.45;
  color: var(--elliot-text-muted);
}
</style>
