# Brand assets

| Asset | Path | Use |
|---|---|---|
| Logo mark | `website/public/logo-mark.svg` | Square favicon-style mark (64×64 viewBox) |
| Favicon | `website/public/favicon.svg` | Browser tab icon |
| OG image (docs) | `website/public/og-image.svg` | 1200×630 — embedded as `<meta property="og:image">` by VitePress |
| GitHub social preview | `website/public/github-social-preview.svg` | 1280×640 — upload as **Settings → General → Social preview** on the GitHub repo |

## Uploading the GitHub social preview

GitHub's social-preview slot only accepts raster (PNG, JPG, GIF) up to 1 MB. Rasterise the SVG before uploading:

```bash
# Using rsvg-convert (Cairo-backed, ~250 KB output)
rsvg-convert -w 1280 -h 640 website/public/github-social-preview.svg \
    -o github-social-preview.png

# Or with sharp (Node)
npx --yes sharp-cli -i website/public/github-social-preview.svg \
    -o github-social-preview.png resize 1280 640

# Or in a browser: open the SVG, screenshot at native resolution
```

Then upload at: **Repository → Settings → General → Social preview → Edit → Upload an image**.

The PNG is intentionally not committed — it's regenerated from the SVG so the SVG remains the source of truth.
