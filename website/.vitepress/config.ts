import { defineConfig } from "vitepress";

const siteUrl = "https://elibarak12.github.io/Elliot/";

// Social-card image. Two hard requirements from real-world link unfurlers
// (Slack, iMessage, X/Twitter, Facebook, LinkedIn, Discord, WhatsApp):
//   1. It must be a RASTER image (PNG/JPG). None of them render SVG og:images,
//      so an SVG card silently falls back to whatever they cached before —
//      which is why the preview kept showing the old logo.
//   2. It must be an ABSOLUTE URL under the deployed base path. A bare
//      "/og-image.svg" both points outside the /Elliot/ base and isn't
//      resolvable by an off-site crawler.
// These platforms also cache previews per-image-URL for a long time, so bump
// `ogImageVersion` whenever the art changes to force every platform to refetch
// instead of serving the stale card.
const ogImageVersion = "20260619";
const ogImage = `${siteUrl}og-image.png?v=${ogImageVersion}`;

// Brand-aligned syntax themes — warm/crimson palette, no blue, so code
// blocks stay on-brand with the rest of the Elliot docs.
const codeThemeLight = {
  name: "elliot-light",
  type: "light" as const,
  colors: { "editor.background": "#f7f7f8", "editor.foreground": "#1f2328" },
  settings: [
    { settings: { foreground: "#1f2328", background: "#f7f7f8" } },
    {
      scope: ["comment", "punctuation.definition.comment"],
      settings: { foreground: "#8a8f98", fontStyle: "italic" },
    },
    {
      scope: ["keyword", "storage", "storage.type", "storage.modifier", "keyword.control", "keyword.operator"],
      settings: { foreground: "#c0303c" },
    },
    {
      scope: ["entity.name.function", "support.function", "meta.function-call.generic"],
      settings: { foreground: "#8f1f29" },
    },
    {
      scope: ["string", "string.quoted", "string.template", "meta.string"],
      settings: { foreground: "#3f6e2f" },
    },
    {
      scope: ["constant.numeric", "constant.language", "constant.character", "constant"],
      settings: { foreground: "#9a5b00" },
    },
    {
      scope: ["entity.name.type", "support.type", "support.class", "entity.name.tag", "entity.name.class"],
      settings: { foreground: "#a3415c" },
    },
    {
      scope: ["variable", "variable.other", "meta.definition.variable", "support.variable"],
      settings: { foreground: "#1f2328" },
    },
    { scope: ["variable.parameter"], settings: { foreground: "#7a4a52" } },
    { scope: ["punctuation", "meta.brace"], settings: { foreground: "#57606a" } },
  ],
};
const codeThemeDark = {
  name: "elliot-dark",
  type: "dark" as const,
  colors: { "editor.background": "#14171c", "editor.foreground": "#e6edf3" },
  settings: [
    { settings: { foreground: "#e6edf3", background: "#14171c" } },
    {
      scope: ["comment", "punctuation.definition.comment"],
      settings: { foreground: "#8b949e", fontStyle: "italic" },
    },
    {
      scope: ["keyword", "storage", "storage.type", "storage.modifier", "keyword.control", "keyword.operator"],
      settings: { foreground: "#e5646e" },
    },
    {
      scope: ["entity.name.function", "support.function", "meta.function-call.generic"],
      settings: { foreground: "#f0a8ae" },
    },
    {
      scope: ["string", "string.quoted", "string.template", "meta.string"],
      settings: { foreground: "#a7d1a0" },
    },
    {
      scope: ["constant.numeric", "constant.language", "constant.character", "constant"],
      settings: { foreground: "#e8a06a" },
    },
    {
      scope: ["entity.name.type", "support.type", "support.class", "entity.name.tag", "entity.name.class"],
      settings: { foreground: "#e58aa0" },
    },
    {
      scope: ["variable", "variable.other", "meta.definition.variable", "support.variable"],
      settings: { foreground: "#e6edf3" },
    },
    { scope: ["variable.parameter"], settings: { foreground: "#d3a9ad" } },
    { scope: ["punctuation", "meta.brace"], settings: { foreground: "#9aa4ad" } },
  ],
};

export default defineConfig({
  title: "Elliot",
  description:
    "Elliot turns any API or database into an agent-ready connector — with minimum tokens, clean error recovery, and full session observability. Build your connector, make your product agent-ready.",
  lang: "en-US",
  cleanUrls: true,
  lastUpdated: true,

  // GitHub Pages serves the site under /Elliot/. Override locally with
  // VITEPRESS_BASE=/ for previewing at the root.
  base: process.env.VITEPRESS_BASE ?? "/Elliot/",

  head: [
    ["link", { rel: "icon", type: "image/svg+xml", href: "/favicon.svg" }],
    ["meta", { name: "theme-color", content: "#c0303c" }],
    ["meta", { property: "og:type", content: "website" }],
    ["meta", { property: "og:title", content: "Elliot — Build your connector. Make your product agent-ready." }],
    [
      "meta",
      {
        property: "og:description",
        content:
          "Turn any API or database into an agent-ready connector. Design, validate, deploy, and observe — one file, one command, every agent.",
      },
    ],
    ["meta", { property: "og:image", content: ogImage }],
    ["meta", { property: "og:image:secure_url", content: ogImage }],
    ["meta", { property: "og:image:type", content: "image/png" }],
    ["meta", { property: "og:image:width", content: "1200" }],
    ["meta", { property: "og:image:height", content: "630" }],
    [
      "meta",
      {
        property: "og:image:alt",
        content: "Elliot — Build your connector. Make your product agent-ready.",
      },
    ],
    ["meta", { property: "og:url", content: siteUrl }],
    ["meta", { name: "twitter:card", content: "summary_large_image" }],
    ["meta", { name: "twitter:image", content: ogImage }],
    [
      "meta",
      {
        name: "twitter:image:alt",
        content: "Elliot — Build your connector. Make your product agent-ready.",
      },
    ],
  ],

  themeConfig: {
    logo: {
      light: "/logo-mark.svg",
      dark: "/logo-mark.svg",
      alt: "Elliot",
    },
    siteTitle: "Elliot",

    nav: [
      { text: "Docs", link: "/docs/introduction", activeMatch: "/docs/" },
      { text: "Quickstart", link: "/docs/quickstart" },
      { text: "Concepts", link: "/docs/concepts" },
      {
        text: "Reference",
        items: [
          { text: "Architecture", link: "/docs/architecture" },
          { text: "Connector spec", link: "/docs/connectors" },
          { text: "CLI", link: "/docs/cli" },
          { text: "Deployment", link: "/docs/deployment" },
        ],
      },
      { text: "GitHub", link: "https://github.com/EliBarak12/Elliot" },
    ],

    sidebar: {
      "/docs/": [
        {
          text: "Get started",
          items: [
            { text: "Introduction", link: "/docs/introduction" },
            { text: "Quickstart", link: "/docs/quickstart" },
            { text: "The five principles", link: "/docs/five-principles" },
            { text: "Agent Experience (AX)", link: "/docs/ax-principles" },
          ],
        },
        {
          text: "Core concepts",
          items: [
            { text: "Concepts", link: "/docs/concepts" },
            { text: "Architecture", link: "/docs/architecture" },
          ],
        },
        {
          text: "Reference",
          items: [
            { text: "Connector spec", link: "/docs/connectors" },
            { text: "CLI", link: "/docs/cli" },
            { text: "Deployment", link: "/docs/deployment" },
          ],
        },
      ],
    },

    socialLinks: [
      { icon: "github", link: "https://github.com/EliBarak12/Elliot" },
    ],

    search: {
      provider: "local",
      options: {
        detailedView: true,
      },
    },

    editLink: {
      pattern:
        "https://github.com/EliBarak12/Elliot/edit/main/website/:path",
      text: "Edit this page on GitHub",
    },

    footer: {
      message:
        'Released under the MIT License. <a href="/Elliot/legal/privacy">Privacy</a> · <a href="/Elliot/legal/terms">Terms</a>',
      copyright: "© 2026 Elliot — built for the agentic web.",
    },

    outline: {
      level: [2, 3],
      label: "On this page",
    },

    docFooter: {
      prev: "Previous",
      next: "Next",
    },
  },

  markdown: {
    theme: {
      light: codeThemeLight,
      dark: codeThemeDark,
    },
    lineNumbers: false,
  },

  ignoreDeadLinks: [
    // Localhost URLs the user visits during dev — not reachable from CI.
    /^https?:\/\/localhost(:\d+)?(\/.*)?$/,
  ],

  sitemap: {
    hostname: siteUrl,
  },
});
