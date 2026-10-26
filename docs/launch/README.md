# Launch-film sources

The 20-second film shows the real application and a quantitative figure generated from the released experiment outputs. It uses no synthetic discoveries, invented curves, fabricated screenshots, voiceover, or stock footage.

- `brag-plan.md` records the product-specific story and nine-question planning rubric.
- `composition-brief.md` and `DESIGN.md` define the handoff and visual identity.
- `build_composition.py` copies authentic source assets into the self-contained `composition/` folder and records input SHA256 values in `sources.json`.
- `make_score.py` creates the original quiet presentation score. Its sound is not scientific data.
- `composition/index.html` is the editable deterministic GSAP/HyperFrames source.
- `launch.mp4` is the final release video; `launch.jpg` is its selected poster.

Rebuild from the repository root after reproducing the scientific results and capturing the current app:

```sh
python docs/launch/make_score.py
python docs/launch/build_composition.py
npx --yes hyperframes@0.8.33 lint docs/launch/composition
npx --yes hyperframes@0.8.33 inspect docs/launch/composition
cd docs/launch/composition
npx --yes hyperframes@0.8.33 render --output ../launch-new.mp4 --fps 30 --quality standard --workers 1
```

The release was rendered through the installed local HyperFrames 0.8.33 wrapper, which disables automatic installation, updates and telemetry and limits process cleanup to owned work. Public CLI rendering requires Node, Chrome and FFmpeg. Native font rasterization and encoding can vary between machines; the original scientific figures and source data remain reproducible independently of video pixels.

The film's layout/contrast/runtime checks and full decode are recorded in `verification.md`. The pinned renderer's motion-audit module is disabled, so sampled current-render frames were inspected directly. Audio is original deterministic synthesis with measured peak levels. No claim of independent listening is implied by a volume check.

## Third-party notice

`composition/assets/gsap.min.js` is GSAP 3.14.2, copyright 2025 GreenSock, authored by Jack Doyle. Its original header is retained. Upstream package metadata identifies the [standard no-charge license](https://gsap.com/standard-license/). The dependency is used to animate this film and is not licensed under MATERIALMIND's MIT license. Original branding, diagrams, composition code, and score-generation source follow the repository code license. Scientific input data and experiment figures retain the repository's separately documented dataset attribution.
