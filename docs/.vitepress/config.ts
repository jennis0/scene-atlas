import { defineConfig } from "vitepress";

export default defineConfig({
  title: "Scene Atlas",
  description: "Search and manage tabletop RPG scenes",

  head: [["meta", { name: "theme-color", content: "#1a1a2e" }]],

  themeConfig: {
    nav: [
      { text: "Guide", link: "/guide/getting-started" },
      { text: "Deploy", link: "/deploy/desktop" },
      {
        text: "GitHub",
        link: "https://github.com/joe-ennis/scene-atlas",
      },
    ],

    sidebar: [
      {
        text: "Getting Started",
        items: [{ text: "Introduction", link: "/guide/getting-started" }],
      },
      {
        text: "User Guide",
        items: [
          { text: "Importing Scenes", link: "/guide/importing" },
          { text: "Searching", link: "/guide/searching" },
          { text: "Groups", link: "/guide/groups" },
        ],
      },
      {
        text: "Deployment",
        items: [
          { text: "Desktop App", link: "/deploy/desktop" },
          { text: "Server", link: "/deploy/server" },
          { text: "Configuration", link: "/deploy/configuration" },
        ],
      },
      {
        text: "Development",
        items: [
          { text: "Building", link: "/development/building" },
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
});
