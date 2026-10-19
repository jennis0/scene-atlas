import DefaultTheme from "vitepress/theme";
import "./custom.css";
import type { Theme } from "vitepress";
import Landing from "./components/Landing.vue";

export default {
  extends: DefaultTheme,
  enhanceApp({ app }) {
    app.component("Landing", Landing);
  },
} satisfies Theme;
