import { defineConfig } from "vitepress";

const ogImage = "/og-image.svg";
const siteUrl = "https://elibarak12.github.io/Elliot/";

export default defineConfig({
  title: "Elliot",
  description:
    "Elliot is the AX (Agent Experience) platform — turn any API or database into agent-native MCP tools with minimum tokens, clean error recovery, and full observability.",
  lang: "en-US",
  cleanUrls: true,
  lastUpdated: true,

  // GitHub Pages serves the site under /Elliot/. Override locally with
  // VITEPRESS_BASE=/ for previewing at the root.
  base: process.env.VITEPRESS_BASE ?? "/Elliot/",

  head: [
    ["link", { rel: "icon", type: "image/svg+xml", href: "/favicon.svg" }],
    ["meta", { name: "theme-color", content: "#00cec8" }],
    ["meta", { property: "og:type", content: "website" }],
    ["meta", { property: "og:title", content: "Elliot — AX Platform for AI Agents" }],
    [
      "meta",
      {
        property: "og:description",
        content:
          "Turn any API or database into agent-native MCP tools. Design, validate, deploy, and observe agent-ready tool sets.",
      },
    ],
    ["meta", { property: "og:image", content: ogImage }],
    ["meta", { property: "og:url", content: siteUrl }],
    ["meta", { name: "twitter:card", content: "summary_large_image" }],
    ["meta", { name: "twitter:image", content: ogImage }],
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
      message: "Released under the MIT License.",
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
      light: "github-light",
      dark: "github-dark",
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
