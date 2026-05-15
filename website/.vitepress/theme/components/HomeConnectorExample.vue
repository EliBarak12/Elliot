<script setup lang="ts">
import { onMounted, ref } from "vue";

const el = ref<HTMLElement | null>(null);

onMounted(() => {
  if (!el.value || typeof IntersectionObserver === "undefined") return;
  const io = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry, i) => {
        if (entry.isIntersecting) {
          const elem = entry.target as HTMLElement;
          elem.style.transitionDelay = `${i * 70}ms`;
          elem.classList.add("is-visible");
          io.unobserve(elem);
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
    <span class="elliot-section__eyebrow">One file. Many actions.</span>
    <h2 class="elliot-section__title">A connector is a declaration, not a service.</h2>
    <p class="elliot-section__lede">
      Describe your sources, the actions you want exposed, and the skills
      agents can chain. Elliot generates safe parameterised SQL, wires auth
      from env vars, and registers your connector with every agent
      automatically.
    </p>

    <div class="elliot-example">
      <div class="elliot-example__code elliot-reveal">
        <div class="elliot-code-bar">
          <span class="elliot-code-dot elliot-code-dot--r"></span>
          <span class="elliot-code-dot elliot-code-dot--y"></span>
          <span class="elliot-code-dot elliot-code-dot--g"></span>
          <span class="elliot-code-file">petstore.connector.json</span>
        </div>
<pre class="elliot-code"><span class="t-p">{</span>
  <span class="t-k">"name"</span><span class="t-p">:</span> <span class="t-s">"Pet Store API"</span><span class="t-p">,</span>
  <span class="t-k">"slug"</span><span class="t-p">:</span> <span class="t-s">"petstore"</span><span class="t-p">,</span>
  <span class="t-k">"version"</span><span class="t-p">:</span> <span class="t-s">"1.0.0"</span><span class="t-p">,</span>
  <span class="t-k">"sources"</span><span class="t-p">:</span> <span class="t-p">[</span>
    <span class="t-p">{</span>
      <span class="t-k">"id"</span><span class="t-p">:</span> <span class="t-s">"animals"</span><span class="t-p">,</span>
      <span class="t-k">"type"</span><span class="t-p">:</span> <span class="t-s">"rest"</span><span class="t-p">,</span>
      <span class="t-k">"url"</span><span class="t-p">:</span> <span class="t-s">"https://api.example.com/animals"</span><span class="t-p">,</span>
      <span class="t-k">"data_path"</span><span class="t-p">:</span> <span class="t-s">"items"</span><span class="t-p">,</span>
      <span class="t-k">"auth"</span><span class="t-p">:</span> <span class="t-p">{</span>
        <span class="t-k">"type"</span><span class="t-p">:</span> <span class="t-s">"api_key"</span><span class="t-p">,</span>
        <span class="t-k">"secret_key"</span><span class="t-p">:</span> <span class="t-s">"PETSTORE_API_KEY"</span><span class="t-p">,</span>
        <span class="t-k">"header_name"</span><span class="t-p">:</span> <span class="t-s">"X-Api-Key"</span>
      <span class="t-p">}</span>
    <span class="t-p">}</span>
  <span class="t-p">]</span><span class="t-p">,</span>
  <span class="t-k">"tools"</span><span class="t-p">:</span> <span class="t-p">[</span>
    <span class="t-p">{</span>
      <span class="t-k">"id"</span><span class="t-p">:</span> <span class="t-s">"list_animals"</span><span class="t-p">,</span>
      <span class="t-k">"description"</span><span class="t-p">:</span> <span class="t-s">"Return all animals, optionally filtered by species."</span><span class="t-p">,</span>
      <span class="t-k">"category"</span><span class="t-p">:</span> <span class="t-s">"READ"</span><span class="t-p">,</span>
      <span class="t-k">"sql"</span><span class="t-p">:</span> <span class="t-s">"SELECT * FROM animals WHERE (:species IS NULL OR species = :species)"</span><span class="t-p">,</span>
      <span class="t-k">"parameters"</span><span class="t-p">:</span> <span class="t-p">[</span>
        <span class="t-p">{</span> <span class="t-k">"name"</span><span class="t-p">:</span> <span class="t-s">"species"</span><span class="t-p">,</span> <span class="t-k">"type"</span><span class="t-p">:</span> <span class="t-s">"string"</span><span class="t-p">,</span> <span class="t-k">"required"</span><span class="t-p">:</span> <span class="t-b">false</span> <span class="t-p">}</span>
      <span class="t-p">]</span>
    <span class="t-p">}</span>
  <span class="t-p">]</span>
<span class="t-p">}</span></pre>
      </div>

      <div class="elliot-example__panels">
        <div class="elliot-panel elliot-reveal">
          <span class="elliot-panel__label">Contract</span>
          <h3 class="elliot-panel__title">Verb-first descriptions</h3>
          <p class="elliot-panel__body">
            Every tool starts with a verb. Categories (READ / WRITE / ACTION)
            tell the agent what side effects to expect.
          </p>
        </div>
        <div class="elliot-panel elliot-reveal">
          <span class="elliot-panel__label">Safety</span>
          <h3 class="elliot-panel__title">Parameterised, never interpolated</h3>
          <p class="elliot-panel__body">
            Named parameters bind through SQLite / driver layers — agents can't
            forge SQL into your runtime, even if a prompt asks them to.
          </p>
        </div>
        <div class="elliot-panel elliot-reveal">
          <span class="elliot-panel__label">Secrets</span>
          <h3 class="elliot-panel__title">Env vars, never strings</h3>
          <p class="elliot-panel__body">
            <code>PETSTORE_API_KEY</code> resolves at request time from your
            environment. Connector files are safe to commit.
          </p>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.elliot-code-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 16px;
  border-bottom: 1px solid var(--elliot-border);
  background: var(--elliot-surface-2);
}
.elliot-code-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  display: inline-block;
}
.elliot-code-dot--r { background: #ff5f57; }
.elliot-code-dot--y { background: #febc2e; }
.elliot-code-dot--g { background: #28c840; }
.elliot-code-file {
  margin-left: 8px;
  font-family: var(--vp-font-family-mono);
  font-size: 0.78rem;
  color: var(--elliot-text-muted);
}
.elliot-code {
  margin: 0;
  padding: 22px 24px;
  font-family: var(--vp-font-family-mono);
  font-size: 0.84rem;
  line-height: 1.65;
  color: var(--vp-c-text-1);
  background: var(--elliot-surface);
  overflow-x: auto;
  tab-size: 2;
  white-space: pre;
}
.t-k { color: var(--vp-c-brand-1); }
.t-s { color: var(--vp-c-text-1); opacity: 0.92; }
.t-p { color: var(--elliot-text-muted); }
.t-b { color: #b07cff; }
.dark .t-b { color: #c79dff; }
</style>
