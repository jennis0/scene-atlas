# Command-Line Tools

Maintenance commands for standalone servers and source checkouts. Run them from the repository root with `uv run`. They use the same configuration as the server (environment variables or `.env`), so set `APP_DATA_DIR` and `IMAGE_LIBRARY_DIR` as you do for the server.

::: warning
Stop the server first. Only one Scene Atlas process can use a library at a time.
:::

In Docker, run them inside the stopped service's container, for example `docker compose --profile cpu run --rm scene-atlas python -m backend.pipeline.export_library /app/images/export`.

## Export the Library

```bash
uv run python -m backend.pipeline.export_library [output-folder]
```

Copies every image into `output-folder` (default `data/exports/<timestamp>`) in folders by author and group, with readable file names and a `metadata.json` holding each image's name, tags and grid. It's the same as **Export library** in Settings, without the ZIP. Images whose files can't be read are skipped and logged.

## Download a Search Model

```bash
uv run python scripts/models/setup_models.py [small|medium|large]
```

Downloads a model ahead of time, for example on a server without internet access at startup. With no argument it downloads `small`.

## Re-run Grid Detection

```bash
uv run python -m backend.pipeline.backfill_grid_detection [--force]
```

Runs grid detection on battlemaps that have no grid information, or no grid size. `--force` re-detects every battlemap. Grids set by hand, and exact sizes or "no grid" from file names, are never changed.

## Regenerate Tags From Names

```bash
uv run python -m backend.pipeline.retag_all_images
```

Removes every tag added automatically and reads them again from file names with the current vocabulary. Tags added by hand are kept. **Regenerate auto-tags** in Manage Tags does the same.

## Re-read Names

```bash
uv run python -m backend.pipeline.reparse_names
```

Cleans every group and image name again with the current name parser, then rebuilds the keyword index. Names you've changed by hand are overwritten.

## Fix Images Without a Group

```bash
uv run python -m backend.pipeline.fix_orphaned_images
```

Puts any image that has lost its group into a group called *Uncategorised*.
