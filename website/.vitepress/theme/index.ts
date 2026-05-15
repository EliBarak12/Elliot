import { h } from "vue";
import type { Theme } from "vitepress";
import DefaultTheme from "vitepress/theme";

import HomePrinciples from "./components/HomePrinciples.vue";
import HomeWorkflow from "./components/HomeWorkflow.vue";
import HomeArchitecture from "./components/HomeArchitecture.vue";
import HomeConnectorExample from "./components/HomeConnectorExample.vue";
import HomeCallout from "./components/HomeCallout.vue";

import "./style.css";

const theme: Theme = {
  extends: DefaultTheme,
  Layout() {
    return h(DefaultTheme.Layout, null, {
      "home-features-after": () => [
        h(HomePrinciples),
        h(HomeWorkflow),
        h(HomeArchitecture),
        h(HomeConnectorExample),
        h(HomeCallout),
      ],
    });
  },
};

export default theme;
