<script setup lang="ts">
import { onMounted, ref } from "vue";

const el = ref<HTMLElement | null>(null);

onMounted(() => {
  if (!el.value || typeof IntersectionObserver === "undefined") return;
  const io = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          (entry.target as HTMLElement).classList.add("is-visible");
          io.unobserve(entry.target);
        }
      });
    },
    { threshold: 0.18 },
  );
  el.value
    .querySelectorAll<HTMLElement>(".elliot-reveal")
    .forEach((item) => io.observe(item));
});
</script>

<template>
  <section ref="el" class="elliot-section">
    <span class="elliot-section__eyebrow">Architecture</span>
    <h2 class="elliot-section__title">Three services. One contract. Any agent.</h2>
    <p class="elliot-section__lede">
      A FastMCP plugin exposes tools, a runtime executes them safely, and
      Studio gives you a glass cockpit for every session.
    </p>

    <div class="elliot-arch elliot-reveal">
      <div class="elliot-arch__svg-wrap">
        <svg
          class="elliot-arch__svg"
          viewBox="0 0 920 440"
          xmlns="http://www.w3.org/2000/svg"
          role="img"
          aria-label="Elliot architecture diagram"
        >
          <defs>
            <linearGradient id="el-teal" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0%" stop-color="#14e5df" />
              <stop offset="100%" stop-color="#008f8b" />
            </linearGradient>
            <linearGradient id="el-pipe" x1="0" y1="0" x2="1" y2="0">
              <stop offset="0%" stop-color="#00cec8" stop-opacity="0" />
              <stop offset="50%" stop-color="#00cec8" stop-opacity="0.9" />
              <stop offset="100%" stop-color="#00cec8" stop-opacity="0" />
            </linearGradient>
            <filter id="el-soft" x="-20%" y="-20%" width="140%" height="140%">
              <feGaussianBlur stdDeviation="6" />
            </filter>
          </defs>

          <!-- Agent column -->
          <g>
            <rect x="40" y="120" width="180" height="200" rx="20"
                  fill="var(--elliot-surface-2)"
                  stroke="var(--elliot-border)" stroke-width="1.5" />
            <text x="130" y="100" text-anchor="middle"
                  font-family="ui-monospace, SF Mono, Menlo"
                  font-size="11" letter-spacing="2"
                  fill="var(--vp-c-brand-1)" font-weight="700">AGENT</text>
            <text x="130" y="160" text-anchor="middle"
                  font-size="14" font-weight="600"
                  fill="var(--vp-c-text-1)">Claude Code</text>
            <text x="130" y="186" text-anchor="middle"
                  font-size="13" fill="var(--vp-c-text-2)">Cursor</text>
            <text x="130" y="208" text-anchor="middle"
                  font-size="13" fill="var(--vp-c-text-2)">Codex</text>
            <text x="130" y="230" text-anchor="middle"
                  font-size="13" fill="var(--vp-c-text-2)">VS Code Copilot</text>
            <text x="130" y="252" text-anchor="middle"
                  font-size="13" fill="var(--vp-c-text-2)">Windsurf</text>
            <text x="130" y="290" text-anchor="middle"
                  font-size="11" font-family="ui-monospace"
                  fill="var(--elliot-text-muted)">any MCP client</text>
          </g>

          <!-- Pipe agent → Elliot -->
          <g>
            <rect x="220" y="216" width="80" height="8" rx="4" fill="url(#el-pipe)" />
            <text x="260" y="206" text-anchor="middle"
                  font-family="ui-monospace, SF Mono"
                  font-size="10" letter-spacing="1.5"
                  fill="var(--vp-c-brand-1)">MCP / HTTP</text>
          </g>

          <!-- Elliot core (3 services) -->
          <g>
            <rect x="300" y="60" width="320" height="320" rx="24"
                  fill="var(--elliot-surface)"
                  stroke="url(#el-teal)" stroke-width="2" />
            <ellipse cx="460" cy="60" rx="220" ry="34"
                     fill="url(#el-teal)" opacity="0.18" filter="url(#el-soft)" />
            <text x="460" y="42" text-anchor="middle"
                  font-family="ui-monospace, SF Mono"
                  font-size="11" letter-spacing="2"
                  fill="var(--vp-c-brand-1)" font-weight="700">ELLIOT</text>

            <!-- mcp-plugin -->
            <g>
              <rect x="324" y="92" width="272" height="78" rx="14"
                    fill="var(--elliot-surface-2)"
                    stroke="var(--elliot-border)" stroke-width="1" />
              <circle cx="346" cy="124" r="6" fill="url(#el-teal)" />
              <text x="362" y="128" font-size="14" font-weight="600"
                    fill="var(--vp-c-text-1)">mcp-plugin</text>
              <text x="362" y="150" font-size="12" fill="var(--vp-c-text-2)">
                FastMCP · :3000 · tool registry
              </text>
            </g>

            <!-- connector-runtime -->
            <g>
              <rect x="324" y="180" width="272" height="78" rx="14"
                    fill="var(--elliot-surface-2)"
                    stroke="var(--elliot-border)" stroke-width="1" />
              <circle cx="346" cy="212" r="6" fill="url(#el-teal)" />
              <text x="362" y="216" font-size="14" font-weight="600"
                    fill="var(--vp-c-text-1)">connector-runtime</text>
              <text x="362" y="238" font-size="12" fill="var(--vp-c-text-2)">
                :3001 · safe SQL · session log
              </text>
            </g>

            <!-- studio -->
            <g>
              <rect x="324" y="268" width="272" height="78" rx="14"
                    fill="var(--elliot-surface-2)"
                    stroke="var(--elliot-border)" stroke-width="1" />
              <circle cx="346" cy="300" r="6" fill="url(#el-teal)" />
              <text x="362" y="304" font-size="14" font-weight="600"
                    fill="var(--vp-c-text-1)">studio</text>
              <text x="362" y="326" font-size="12" fill="var(--vp-c-text-2)">
                React 19 · :5173 · observe & edit
              </text>
            </g>
          </g>

          <!-- Pipe Elliot → sources -->
          <g>
            <rect x="620" y="216" width="80" height="8" rx="4" fill="url(#el-pipe)" />
            <text x="660" y="206" text-anchor="middle"
                  font-family="ui-monospace, SF Mono"
                  font-size="10" letter-spacing="1.5"
                  fill="var(--vp-c-brand-1)">HTTP / SQL</text>
          </g>

          <!-- Sources column -->
          <g>
            <rect x="700" y="120" width="180" height="200" rx="20"
                  fill="var(--elliot-surface-2)"
                  stroke="var(--elliot-border)" stroke-width="1.5" />
            <text x="790" y="100" text-anchor="middle"
                  font-family="ui-monospace, SF Mono"
                  font-size="11" letter-spacing="2"
                  fill="var(--vp-c-brand-1)" font-weight="700">SOURCES</text>
            <text x="790" y="160" text-anchor="middle"
                  font-size="14" font-weight="600"
                  fill="var(--vp-c-text-1)">REST APIs</text>
            <text x="790" y="186" text-anchor="middle"
                  font-size="13" fill="var(--vp-c-text-2)">PostgreSQL</text>
            <text x="790" y="208" text-anchor="middle"
                  font-size="13" fill="var(--vp-c-text-2)">MySQL</text>
            <text x="790" y="230" text-anchor="middle"
                  font-size="13" fill="var(--vp-c-text-2)">CSV · JSON</text>
            <text x="790" y="252" text-anchor="middle"
                  font-size="13" fill="var(--vp-c-text-2)">Local files</text>
            <text x="790" y="290" text-anchor="middle"
                  font-size="11" font-family="ui-monospace"
                  fill="var(--elliot-text-muted)">your existing data</text>
          </g>

          <!-- Bottom rail: observability -->
          <g>
            <rect x="40" y="396" width="840" height="32" rx="10"
                  fill="var(--vp-c-brand-soft)"
                  stroke="var(--vp-c-brand-3)" stroke-width="1" stroke-dasharray="3 3" />
            <text x="460" y="417" text-anchor="middle"
                  font-family="ui-monospace, SF Mono"
                  font-size="11" letter-spacing="1.5"
                  fill="var(--vp-c-brand-1)" font-weight="600">
              every call: tokens · latency · args · result · error → NDJSON audit log
            </text>
          </g>
        </svg>
      </div>
    </div>
  </section>
</template>
