<script setup lang="ts">
import { withBase } from "vitepress";
import {
  MARK_BANDS,
  MARK_PAGES,
  MARK_VIEWBOX,
} from "../../../../frontend/src/components/brand/markPaths";

const REPO = "https://github.com/jennis0/scene-atlas";

// File names as they arrive from downloads, beside what you'd actually type.
const examples = [
  { file: "IMG_2048.jpg", query: "flooded crypt" },
  { file: "final_v3_gridless.png", query: "market square at dusk" },
  { file: "Map 17 (Night).webp", query: "woodland path at night" },
  { file: "forest-pack-04-loop.mp4", query: "campfire in a forest clearing" },
];

const features = [
  {
    title: "Bring your whole collection",
    body: "Use the folder you already keep your maps in, without copying it, or import folders and zip files with duplicates skipped.",
  },
  {
    title: "Variants together",
    body: "The day, night, winter and gridless versions of a map stay grouped as one.",
  },
  {
    title: "Animated maps",
    body: "MP4 and WebM maps are imported, searched and played alongside the rest.",
  },
  {
    title: "Grid detection",
    body: "Square and hex grids found on battlemaps, so you know the grid before it goes into your VTT.",
  },
  {
    title: "Filters",
    body: "By type, grid, colour and tags, with tag packs for fantasy, sci-fi, horror, cyberpunk and historical games.",
  },
  {
    title: "Handles big libraries",
    body: "Tested with over 56,000 images.",
  },
];

const NUMERALS = ["I", "II", "III", "IV", "V", "VI"];

const ways = [
  {
    title: "Desktop app",
    body: "Windows, macOS on Apple Silicon, and Linux.",
    link: "/deploy/desktop",
    action: "Download",
  },
  {
    title: "Docker",
    body: "For a home server or NAS.",
    link: "/deploy/server",
    action: "Self-host with Docker",
  },
  {
    title: "Standalone server",
    body: "Run the server without Docker.",
    link: "/deploy/standalone",
    action: "Set it up",
  },
];
</script>

<template>
  <div class="landing">
    <section class="hero">
      <div class="wordmark">
        <svg
          :viewBox="MARK_VIEWBOX"
          class="mark"
          aria-hidden="true"
          focusable="false"
        >
          <path v-for="d in MARK_BANDS" :key="d" :d="d" class="band" />
          <path v-for="d in MARK_PAGES" :key="d" :d="d" class="page" />
        </svg>
        <h1>Scene Atlas</h1>
      </div>
      <p class="tagline">Art and map management for game masters.</p>
      <p class="lede">
        Describe the map you need, like “flooded crypt” or “market square at
        dusk”, and Scene Atlas finds it by what's in the image, not what the
        file is called. Drop in the folders and zips from your map downloads and
        it groups the variants and detects the grid.
      </p>
      <div class="actions">
        <a class="button primary" :href="withBase('/deploy/desktop')"
          >Download</a
        >
        <a class="button" :href="withBase('/guide/what-is-scene-atlas')"
          >Read the guide</a
        >
      </div>
      <p class="meta">
        Free and open source <span aria-hidden="true">·</span> Windows, macOS,
        Linux, and self-hosted <span aria-hidden="true">·</span> All data stays on your machine
      </p>
    </section>

    <figure class="plate">
      <img
        :src="withBase('/screenshots/search.webp')"
        width="1440"
        height="797"
        alt="Scene Atlas showing results for “woodland path at night”: groups of battlemap variants from three creators, each led by its night-time version, in dark and light themes"
      />
      <figcaption>
        Searching “woodland path at night”. Maps by
        <a href="https://www.moonlight-maps.com">Moonlight Maps</a> (CC BY-NC-SA
        4.0), <a href="https://2minutetabletop.com">2-Minute Tabletop</a> (CC
        BY-NC 4.0) and
        <a href="https://www.patreon.com/fantasy_atlas">Fantasy Atlas</a> (CC
        BY-NC 4.0). Support them on Patreon! This screenshot is shared under CC
        BY-NC-SA 4.0.
      </figcaption>
    </figure>

    <section class="search">
      <div class="copy">
        <h2>Search by content</h2>
        <p>
          Scene Atlas looks at every image as it comes in, so you can find a map
          by describing it. Name, creator and tag searches still work, and you
          can narrow results by grid, colour and type.
        </p>
        <a class="more" :href="withBase('/guide/searching')"
          >How searching works</a
        >
      </div>
      <table class="ledger">
        <thead>
          <tr>
            <th scope="col">The file is called</th>
            <th scope="col">You search for</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in examples" :key="row.file">
            <td>
              <code>{{ row.file }}</code>
            </td>
            <td>{{ row.query }}</td>
          </tr>
        </tbody>
      </table>
    </section>

    <section class="features" aria-labelledby="features-heading">
      <h2 id="features-heading">Built for your maps</h2>
      <ol>
        <li v-for="(f, i) in features" :key="f.title">
          <span class="numeral" aria-hidden="true">{{ NUMERALS[i] }}</span>
          <h3>{{ f.title }}</h3>
          <p>{{ f.body }}</p>
        </li>
      </ol>
    </section>

    <section class="ways" aria-labelledby="ways-heading">
      <h2 id="ways-heading">Run it your way</h2>
      <p class="intro">
        However you run it, everything stays
        on your machine.
      </p>
      <div class="cards">
        <a
          v-for="w in ways"
          :key="w.title"
          class="card"
          :href="withBase(w.link)"
        >
          <h3>{{ w.title }}</h3>
          <p>{{ w.body }}</p>
          <span class="action"
            >{{ w.action }} <span aria-hidden="true">→</span></span
          >
        </a>
      </div>
    </section>

    <section class="closing">
      <p>
        Scene Atlas is free and open source under the MIT licence.
        <a :href="REPO">Source, issues and releases are on GitHub</a>.
      </p>
    </section>
  </div>
</template>

<style scoped>
.landing {
  --gutter: 24px;
  --measure: 1152px;
  --ease: cubic-bezier(0.2, 0.7, 0.2, 1);
  padding: 0 var(--gutter) 32px;
  overflow-x: clip;
}

@media (max-width: 640px) {
  .landing {
    --gutter: 16px;
  }
}

.landing h1,
.landing h2,
.landing h3,
.numeral {
  font-family: "Cinzel", Georgia, serif;
  font-weight: 500;
  color: var(--vp-c-text-1);
}

.landing a:not(.button):not(.card) {
  color: var(--vp-c-brand-1);
  text-decoration: underline;
  text-decoration-color: color-mix(
    in srgb,
    var(--vp-c-brand-1) 40%,
    transparent
  );
  text-underline-offset: 3px;
  transition: text-decoration-color 0.2s;
}

.landing a:not(.button):not(.card):hover {
  text-decoration-color: currentColor;
}

/* ── Hero ───────────────────────────────────────────────────── */

.hero {
  position: relative;
  max-width: 820px;
  margin: 0 auto;
  padding: 72px 0 48px;
  text-align: center;
}

.hero::before {
  content: "";
  position: absolute;
  inset: -40px -30vw auto;
  height: 620px;
  background: radial-gradient(
    ellipse 50% 60% at 50% 30%,
    var(--vp-c-brand-soft),
    transparent 70%
  );
  pointer-events: none;
  z-index: -1;
}

.hero > * {
  animation: rise 0.8s var(--ease) both;
}

.hero > :nth-child(2) {
  animation-delay: 0.08s;
}
.hero > :nth-child(3) {
  animation-delay: 0.16s;
}
.hero > :nth-child(4) {
  animation-delay: 0.24s;
}
.hero > :nth-child(5) {
  animation-delay: 0.32s;
}

/* Matches the lockup: mark at 0.85em, 0.45em from the name, 0.04em tracking */
.wordmark {
  display: inline-flex;
  align-items: center;
  gap: 0.45em;
  font-size: clamp(2.6rem, 1.4rem + 5vw, 4.75rem);
}

.mark {
  height: 0.85em;
  width: auto;
  flex-shrink: 0;
}

.band {
  fill: var(--vp-c-brand-1);
}

.page {
  fill: var(--sa-mark-page);
}

.wordmark h1 {
  font-size: 1em;
  line-height: 1;
  letter-spacing: 0.04em;
}

.tagline {
  margin-top: 20px;
  font-size: clamp(1.2rem, 1rem + 1vw, 1.6rem);
  font-weight: 500;
  line-height: 1.35;
  color: var(--vp-c-text-1);
}

.lede {
  max-width: 62ch;
  margin: 20px auto 0;
  font-size: 1.05rem;
  line-height: 1.7;
  color: var(--vp-c-text-2);
}

.actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 12px;
  margin-top: 32px;
}

.button {
  display: inline-block;
  padding: 0 22px;
  line-height: 44px;
  border-radius: 8px;
  border: 1px solid var(--vp-c-border);
  background: var(--vp-c-default-soft);
  color: var(--vp-c-text-1);
  font-weight: 600;
  font-size: 0.95rem;
  transition:
    background-color 0.2s,
    border-color 0.2s,
    transform 0.2s var(--ease);
}

.button:hover {
  border-color: var(--vp-c-brand-1);
  transform: translateY(-1px);
}

.button.primary {
  border-color: var(--vp-c-brand-1);
  background: var(--vp-c-brand-1);
  color: var(--vp-c-bg);
}

.button.primary:hover {
  background: var(--vp-c-brand-3);
  border-color: var(--vp-c-brand-3);
}

.meta {
  margin-top: 24px;
  font-size: 0.85rem;
  letter-spacing: 0.02em;
  color: var(--vp-c-text-3);
}

/* ── Screenshot plate ───────────────────────────────────────── */

.plate {
  max-width: var(--measure);
  margin: 0 auto;
  animation: rise 1s var(--ease) 0.4s both;
}

.plate img {
  display: block;
  width: 100%;
  height: auto;
  border-radius: 10px;
  border: 1px solid var(--vp-c-border);
  box-shadow:
    0 0 0 6px var(--vp-c-bg-soft),
    0 0 0 7px var(--vp-c-border),
    0 30px 80px -20px rgba(0, 0, 0, 0.45);
}

.plate figcaption {
  max-width: 820px;
  margin: 28px auto 0;
  text-align: center;
  font-size: 0.8rem;
  line-height: 1.6;
  color: var(--vp-c-text-3);
}

/* ── Search by content ──────────────────────────────────────── */

.search {
  display: grid;
  grid-template-columns: minmax(0, 5fr) minmax(0, 6fr);
  gap: 56px;
  align-items: center;
  max-width: var(--measure);
  margin: 120px auto 0;
}

.landing h2 {
  font-size: clamp(1.6rem, 1.2rem + 1.6vw, 2.25rem);
  line-height: 1.2;
  letter-spacing: 0.01em;
}

.copy p {
  margin-top: 16px;
  font-size: 1.05rem;
  line-height: 1.7;
  color: var(--vp-c-text-2);
}

.more {
  display: inline-block;
  margin-top: 16px;
  font-weight: 500;
}

.ledger {
  display: table;
  width: 100%;
  margin: 0;
  border-collapse: collapse;
  border: none;
}

.ledger tr {
  border: none;
  background: none;
}

.ledger th {
  padding: 0 0 12px;
  border: none;
  border-bottom: 1px solid var(--vp-c-brand-1);
  background: none;
  text-align: left;
  font-size: 0.75rem;
  font-weight: 600;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--vp-c-text-3);
}

.ledger td {
  padding: 18px 16px 18px 0;
  border: none;
  border-bottom: 1px solid var(--vp-c-divider);
  background: none;
  vertical-align: baseline;
}

.ledger td:first-child {
  width: 46%;
}

.ledger code {
  padding: 0;
  background: none;
  font-family: var(--vp-font-family-mono);
  font-size: 0.85rem;
  color: var(--vp-c-text-3);
  overflow-wrap: anywhere;
}

.ledger td:last-child {
  font-family: "Cinzel", Georgia, serif;
  font-size: 1.15rem;
  color: var(--vp-c-text-1);
}

/* ── Features ───────────────────────────────────────────────── */

.features,
.ways {
  max-width: var(--measure);
  margin: 120px auto 0;
}

.features ol {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 40px 48px;
  margin: 40px 0 0;
  padding: 0;
  list-style: none;
}

.features li {
  padding-top: 20px;
  border-top: 1px solid var(--vp-c-border);
}

.numeral {
  display: block;
  font-size: 0.85rem;
  letter-spacing: 0.12em;
  color: var(--vp-c-brand-1);
}

.landing h3 {
  margin-top: 10px;
  font-size: 1.2rem;
  line-height: 1.3;
}

.features p,
.card p {
  margin-top: 8px;
  line-height: 1.65;
  color: var(--vp-c-text-2);
}

/* ── Ways to run ────────────────────────────────────────────── */

.ways .intro {
  max-width: 62ch;
  margin-top: 16px;
  font-size: 1.05rem;
  line-height: 1.7;
  color: var(--vp-c-text-2);
}

.cards {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 20px;
  margin-top: 40px;
}

.card {
  display: flex;
  flex-direction: column;
  padding: 28px;
  border-radius: 10px;
  border: 1px solid var(--vp-c-border);
  background: var(--vp-c-bg-soft);
  color: inherit;
  transition:
    border-color 0.2s,
    transform 0.2s var(--ease);
}

.card:hover {
  border-color: var(--vp-c-brand-1);
  transform: translateY(-2px);
}

.card h3 {
  margin-top: 0;
}

.card p {
  flex: 1;
}

.action {
  margin-top: 20px;
  font-weight: 600;
  font-size: 0.95rem;
  color: var(--vp-c-brand-1);
}

/* ── Closing ────────────────────────────────────────────────── */

.closing {
  max-width: var(--measure);
  margin: 120px auto 0;
  padding-top: 32px;
  border-top: 1px solid var(--vp-c-divider);
  text-align: center;
  color: var(--vp-c-text-2);
}

/* ── Layout at narrower widths ──────────────────────────────── */

@media (max-width: 960px) {
  .search {
    grid-template-columns: minmax(0, 1fr);
    gap: 40px;
  }

  .features ol {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .cards {
    grid-template-columns: minmax(0, 1fr);
  }
}

@media (max-width: 640px) {
  .hero {
    padding-top: 48px;
  }

  .features ol {
    grid-template-columns: minmax(0, 1fr);
    gap: 32px;
  }

  .search,
  .features,
  .ways,
  .closing {
    margin-top: 80px;
  }

  .ledger td:last-child {
    font-size: 1rem;
  }
}

@keyframes rise {
  from {
    opacity: 0;
    transform: translateY(14px);
  }
}

@media (prefers-reduced-motion: reduce) {
  .hero > *,
  .plate {
    animation: none;
  }

  .button,
  .card {
    transition: none;
  }
}
</style>
