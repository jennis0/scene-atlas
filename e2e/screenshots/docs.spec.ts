// The docs screenshots, from a running demo instance (design/brand.md#screenshots).
//
// Everything shown is the real app on the demo library, except what only the desktop app
// can provide: its bridge (window.electronAPI, with made-up folder paths) and the folder
// check for those paths. Both are typed against the frontend's own types, so a change to
// either breaks the type check rather than the screenshot.
//
// Run with: npm run docs:screenshots (needs DEMO_URL and DEMO_HELD, see design/brand.md)
import { expect, test, type Locator, type Page } from "@playwright/test";
import path from "path";
import type { ElectronAPI, StorageDirs } from "../../frontend/src/electron";
import type { InspectResult } from "../../frontend/src/lib/api/libraryApi";
import type { SetupStatus } from "../../frontend/src/lib/api/modelsApi";
import {
  openImportDialog,
  searchFor,
  waitForImportFinished,
} from "../helpers/actions";

const OUT = path.resolve(__dirname, "..", "test-results-screenshots", "png");
/** held/ from scripts/demo/docs_library.py: packs the run imports through the UI */
const HELD = process.env.DEMO_HELD ?? "";

/** Made-up desktop folders: never a real person's paths */
const DIRS: StorageDirs = {
  appData: "C:\\Users\\GM\\AppData\\Local\\Scene Atlas\\data",
  store: "D:\\Battle Maps\\Scene Atlas",
  linked: "D:\\Battle Maps",
  defaults: {
    appData: "C:\\Users\\GM\\AppData\\Local\\Scene Atlas\\data",
    store: "C:\\Users\\GM\\AppData\\Local\\Scene Atlas\\images",
  },
};

/** Space kept around an element, so the shot shows it sitting in the app */
const PAD = 24;

/** The whole window, or an element with PAD of the window around it (clamped to it) */
async function shot(target: Page | Locator, name: string): Promise<void> {
  const file = path.join(OUT, `${name}.png`);
  if ("goto" in target) {
    await target.screenshot({ path: file, animations: "disabled" });
    return;
  }
  const page = target.page();
  // The padding shows the app behind the element, but not its art: that would need
  // crediting too (design/brand.md#screenshots)
  await target.evaluate((el) => {
    for (const media of document.querySelectorAll<HTMLElement>("img, video")) {
      if (!el.contains(media)) media.style.visibility = "hidden";
    }
  });
  const box = await target.boundingBox();
  const view = page.viewportSize();
  if (!box || !view) throw new Error(`${name}: nothing to capture`);
  const x = Math.max(0, box.x - PAD);
  const y = Math.max(0, box.y - PAD);
  await page.screenshot({
    path: file,
    animations: "disabled",
    clip: {
      x,
      y,
      width: Math.min(view.width, box.x + box.width + PAD) - x,
      height: Math.min(view.height, box.y + box.height + PAD) - y,
    },
  });
}

/** Let thumbnails finish fading in */
async function settle(page: Page): Promise<void> {
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(1500);
}

async function openGallery(page: Page): Promise<void> {
  await page.goto("/");
  await expect(page.getByRole("group", { name: "Image type" })).toBeVisible();
  await settle(page);
}

/** The desktop app's bridge, as the preload script would provide it */
async function asDesktopApp(
  page: Page,
  { libraryChosen }: { libraryChosen: boolean },
): Promise<void> {
  await page.addInitScript(
    ({ dirs, libraryChosen }) => {
      const done = async () => {};
      const noState = async () => null;
      const api: ElectronAPI = {
        platform: "win32",
        displayPrefs: {},
        setDisplayPref: done,
        setWindowColors: done,
        onBackendError: () => () => {},
        retryStartup: done,
        chooseFoldersAgain: done,
        libraryChosen,
        getStorageDirs: async () => dirs,
        chooseFolder: async (kind) => (kind === "linked" ? dirs.linked : null),
        applyLibrary: async () => ({ error: null, restarted: false }),
        restartBackend: async () => false,
        getPathForFile: () => "",
        chooseImportFolders: async () => [],
        chooseImportFiles: async () => [],
        setZoom: () => {},
        getUpdateState: noState,
        checkForUpdates: noState,
        setUpdateChoice: noState,
        downloadUpdate: noState,
        installUpdate: done,
        openUpdateDownload: done,
        onUpdateState: () => () => {},
      };
      window.electronAPI = api;
    },
    { dirs: DIRS, libraryChosen },
  );
}

test("gallery", async ({ page }) => {
  await openGallery(page);
  await page
    .getByRole("group", { name: "Image type" })
    .getByRole("button", { name: /Maps/ })
    .click();
  await page.getByTitle("Groups").click();
  await settle(page);
  await page.screenshot({
    path: path.join(OUT, "gallery.png"),
    // Two rows of cards: the newest groups, all Moonlight Maps (credited on the page)
    clip: { x: 0, y: 0, width: 1440, height: 612 },
  });
});

test("filters", async ({ page }) => {
  await openGallery(page);
  await page.getByTitle("Groups").click();
  await page.getByTitle("Filters").click();
  const menu = page.getByRole("dialog");
  await menu.getByRole("button", { name: "environment", exact: true }).click();
  await settle(page);
  await shot(menu, "filters");
});

test("viewer", async ({ page }) => {
  // Campfire Stories is Fantasy Atlas, CC BY-NC 4.0: shown at viewer size with its credit
  await openGallery(page);
  await page.getByTitle("Individual images").click();
  await searchFor(page, '="Campfire Stories"');
  // The gridded and gridless variants share a name: keep the gridded ones
  await page.getByTitle("Filters").click();
  const filters = page.getByRole("dialog");
  await filters.getByRole("button", { name: "Grid", exact: true }).click();
  await filters.getByRole("button", { name: "Square", exact: true }).click();
  await page.keyboard.press("Escape");
  await settle(page);
  await page
    .getByRole("button", { name: /Campfire Stories - Night Campfire, by/ })
    .first()
    .click();
  const viewer = page.getByTestId("image-viewer");
  await expect(viewer).toBeVisible();
  await page.keyboard.press("g");
  await settle(page);
  await shot(page, "viewer");
});

test("group editor", async ({ page }) => {
  await openGallery(page);
  await page.getByTitle("Groups").click();
  await searchFor(page, '="Campfire Stories"');
  await settle(page);
  await page
    .getByRole("button", { name: /Actions for Campfire Stories/ })
    .first()
    .click();
  await page.getByRole("menuitem", { name: "Edit" }).click();
  const editor = page.getByRole("dialog");
  await expect(editor).toBeVisible();
  await settle(page);
  await shot(editor, "group-editor");
});

test("import: dialog, progress and report", async ({ page }) => {
  test.skip(!HELD, "DEMO_HELD is not set");
  test.setTimeout(15 * 60_000);
  await openGallery(page);
  await openImportDialog(page);
  const dialog = page.getByRole("dialog");
  await shot(dialog, "import-dialog");

  const chooser = page.waitForEvent("filechooser");
  await dialog.getByRole("button", { name: "Choose a folder" }).click();
  await (await chooser).setFiles(path.join(HELD, "2 Minute Tabletop"));
  await expect(dialog.getByText(/of \d+ files/)).toBeVisible({
    timeout: 60_000,
  });
  await page.waitForTimeout(4000); // some groups part-way
  await shot(dialog, "import-progress");

  await waitForImportFinished(page, 10 * 60_000);
  await settle(page);
  await shot(dialog, "import-report");

  // Leave the library as it was, so the run can be repeated
  await dialog.getByRole("button", { name: "Undo import" }).click();
  await page
    .getByRole("alertdialog", { name: "Undo this import?" })
    .getByRole("button", { name: "Delete imported images" })
    .click();
  await expect(page.getByText(/Import undone/)).toBeVisible({
    timeout: 60_000,
  });
});

test("settings: library tab", async ({ page }) => {
  await openGallery(page);
  await page.getByTitle("Settings", { exact: true }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByText("My Maps")).toBeVisible();
  await settle(page);
  await shot(dialog, "settings-library");
});

test("settings: storage locations (desktop)", async ({ page }) => {
  await asDesktopApp(page, { libraryChosen: true });
  await openGallery(page);
  await page.getByTitle("Settings", { exact: true }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("tab", { name: "Settings" }).click();
  const section = dialog.locator("section", {
    has: page.getByRole("heading", { name: "Storage locations" }),
  });
  await expect(section).toContainText(DIRS.linked ?? "");
  await settle(page);
  await shot(section, "settings-storage");
});

test("setup: your library (desktop)", async ({ page }) => {
  await asDesktopApp(page, { libraryChosen: false });
  // A first launch: setup not finished, and the folder check for the made-up folder
  await page.route("**/api/v1/models/setup-status", async (route) => {
    const real = (await (await route.fetch()).json()) as SetupStatus;
    const status: SetupStatus = { ...real, setup_completed: false };
    await route.fulfill({ json: status });
  });
  await page.route("**/api/v1/library/inspect", async (route) => {
    const result: InspectResult = {
      outcome: "new",
      message: null,
      linked: { kind: "maps", image_count: 4_218, capped: false },
      library: null,
      store_has_maps: false,
    };
    await route.fulfill({ json: result });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Continue" }).click();
  // Choosing the option opens the folder picker, which the stand-in answers
  await page
    .getByText("Link a library you already have", { exact: true })
    .click();
  await expect(page.getByText("Found 4,218 images.")).toBeVisible();
  // The wizard's column, without the empty window either side
  await page.screenshot({
    path: path.join(OUT, "setup-library.png"),
    clip: { x: 320, y: 30, width: 800, height: 750 },
  });
});
