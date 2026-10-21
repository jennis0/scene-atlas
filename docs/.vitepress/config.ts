import { defineConfig } from "vitepress";

const SITE = "https://jennis0.github.io/scene-atlas";

export default defineConfig({
  title: "Scene Atlas",
  description:
    "Art and map management for game masters. Search battlemaps and scene art by what's in them, keep variants together, and run it on your desktop or your own server.",

  // Served from https://jennis0.github.io/scene-atlas/
  base: "/scene-atlas/",

  head: [
    ["meta", { name: "theme-color", content: "#0e1118" }],
    // head entries aren't prefixed with base, so these carry it themselves
    [
      "link",
      { rel: "icon", type: "image/svg+xml", href: "/scene-atlas/favicon.svg" },
    ],
    ["meta", { property: "og:type", content: "website" }],
    ["meta", { property: "og:site_name", content: "Scene Atlas" }],
    ["meta", { property: "og:image", content: `${SITE}/social-preview.png` }],
    ["meta", { property: "og:image:width", content: "1280" }],
    ["meta", { property: "og:image:height", content: "640" }],
    ["meta", { name: "twitter:card", content: "summary_large_image" }],
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
        href: "https://fonts.googleapis.com/css2?family=Cinzel:wght@400;500;600;700&family=Figtree:ital,wght@0,300;0,400;0,500;0,600;1,400&family=JetBrains+Mono:wght@400;500&display=swap",
      },
    ],
  ],

  themeConfig: {
    logo: "/favicon.svg",
    nav: [
      { text: "Guide", link: "/guide/what-is-scene-atlas" },
      { text: "Deploy", link: "/deploy/desktop" },
      { text: "Reference", link: "/deploy/configuration" },
      // Configuration stays under /deploy/: the README and the app link to it
      { text: "Development", link: "/development/building" },
      {
        text: "GitHub",
        link: "https://github.com/jennis0/scene-atlas",
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
          { text: "Your Library", link: "/guide/library" },
          { text: "Importing", link: "/guide/importing" },
          { text: "Gallery & Image Viewer", link: "/guide/gallery" },
          { text: "Searching", link: "/guide/searching" },
          { text: "Groups & Variants", link: "/guide/groups" },
          { text: "Tags", link: "/guide/tags" },
          { text: "Settings", link: "/guide/settings" },
        ],
      },
      {
        text: "Deployment",
        items: [
          { text: "Desktop App", link: "/deploy/desktop" },
          { text: "Docker Server", link: "/deploy/server" },
          { text: "Standalone Server", link: "/deploy/standalone" },
        ],
      },
      {
        text: "Reference",
        items: [
          {
            text: "Configuration",
            link: "/deploy/configuration",
          },
          { text: "How Search Works", link: "/reference/search" },
          { text: "Command-Line Tools", link: "/reference/cli" },
          { text: "Troubleshooting", link: "/reference/troubleshooting" },
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
        link: "https://github.com/jennis0/scene-atlas",
      },
    ],
  },

  appearance: "dark",

  // Exclude internal planning docs from the public site
  srcExclude: ["**/plans/**", "**/superpowers/**"],
});
