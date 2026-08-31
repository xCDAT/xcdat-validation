# RIOTAI presentations

## Environment setup

Run these commands from the repository root. The environment includes the
xCDAT/RIOTAI dependencies, JupyterLab 4, `jupyterlab_rise`, and `nbconvert`.

```bash
conda env create --file riotai/presentations/environment.yml
conda activate riotai-presentation
jupyter lab riotai/presentations/starter-presentation.ipynb
```

## Edit slides

In JupyterLab, open the Property Inspector (the cog icon at the top right), then
use the Common Tools tab to assign each cell one of these slide types:

- **Slide** starts a new horizontal topic.
- **Sub-Slide** adds vertical detail beneath that topic.
- **Fragment** reveals supporting content incrementally.
- **Skip** excludes the cell from the presentation.
- **Notes** adds presenter-only notes.

See the [`jupyterlab_rise` usage
guide](https://github.com/jupyterlab-contrib/rise#usage) for more details.

## Present slides

Start the live presentation with `Ctrl+R` (`Option+R` on macOS). RISE keeps the
notebook kernel active, so you can edit or execute code while presenting and
then return to the prepared narrative.

Use the arrow keys or Reveal.js controls to navigate. Press `Esc` for the slide
overview.

If live presentation mode is unavailable, verify both parts of the extension:

```bash
jupyter server extension list
jupyter labextension list
```

## Add portable images

Prefer notebook-generated figures, images attached to Markdown cells, or
relative image paths. Avoid absolute paths and remote-only image URLs. Dragging
an image into an edited Markdown cell creates an attachment.

For an external image stored beside the notebook, use a relative Markdown path:

```markdown
![Description](image.svg)
```

The `--embed-images` export option places these images inside the generated
HTML, so the exported presentation has no separate image dependency.

## Export slides

Before exporting, run all cells so generated figures are stored as notebook
outputs. Export executable Reveal.js slides with embedded Markdown images from
the repository root:

```bash
jupyter nbconvert \
  --to slides \
  --execute \
  --embed-images \
  --output starter-presentation \
  riotai/presentations/starter-presentation.ipynb
```

This writes `starter-presentation.slides.html`. The slideshow still loads
Reveal.js from its configured CDN. To make the presentation fully offline, use
`--reveal-prefix` with a local Reveal.js copy.
