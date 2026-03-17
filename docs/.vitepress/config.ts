import { defineConfig } from "vitepress";

export default defineConfig({
  title: "Scene Atlas",
  description:
    "AI-powered scene manager for tabletop RPG art — search, organise, and deploy your battlemap collection",

  head: [
    ["meta", { name: "theme-color", content: "#0e1118" }],
    ["link", { rel: "icon", type: "image/svg+xml", href: "/favicon.svg" }],
    ["link", { rel: "preconnect", href: "https://fonts.googleapis.com" }],
    [
      "link",
      {
        rel: "preconnect",
        href: "https://fonts.gstatic.com",
        crossorigin: "",
      },
    ],
    [
      "link",
      {
        rel: "stylesheet",
        href: "https://fonts.googleapis.com/css2?family=Cinzel:wght@400;600;700&family=Figtree:ital,wght@0,300;0,400;0,500;0,600;1,400&family=JetBrains+Mono:wght@400;500&display=swap",
      },
    ],
  ],

  themeConfig: {
    nav: [
      { text: "Guide", link: "/guide/what-is-scene-atlas" },
      { text: "Deploy", link: "/deploy/desktop" },
      { text: "Development", link: "/development/building" },
      {
        text: "GitHub",
        link: "https://github.com/joe-ennis/scene-atlas",
      },
    ],

    sidebar: [
      {
        text: "Getting Started",
        items: [
          {
            text: "What is Scene Atlas?",
            link: "/guide/what-is-scene-atlas",
          },
          { text: "Installation", link: "/guide/getting-started" },
        ],
      },
      {
        text: "Using Scene Atlas",
        items: [
          { text: "Importing Scenes", link: "/guide/importing" },
          { text: "Searching", link: "/guide/searching" },
          { text: "Groups & Variants", link: "/guide/groups" },
          { text: "Tags & Filtering", link: "/guide/tags" },
          { text: "Gallery Views", link: "/guide/gallery" },
        ],
      },
      {
        text: "Deployment",
        items: [
          { text: "Desktop App", link: "/deploy/desktop" },
          { text: "Docker Server", link: "/deploy/server" },
          { text: "Standalone Server", link: "/deploy/standalone" },
          {
            text: "Configuration Reference",
            link: "/deploy/configuration",
          },
        ],
      },
      {
        text: "Development",
        items: [
          { text: "Building & Running", link: "/development/building" },
          { text: "Testing", link: "/development/testing" },
          { text: "Stress Testing", link: "/development/stress-testing" },
        ],
      },
    ],

    search: {
      provider: "local",
    },

    socialLinks: [
      {
        icon: "github",
        link: "https://github.com/joe-ennis/scene-atlas",
      },
    ],
  },

  appearance: "dark",

  ignoreDeadLinks: [
    // Pre-existing links in development/plans that point to backend source files
    /\.\/backend\//,
    /\.\/\.\.\/\.\.\//,
  ],
});
