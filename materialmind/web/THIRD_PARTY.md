# Browser dependencies

The `vendor/` directory contains unmodified browser distribution files from **Three.js 0.180.0**, released under the MIT License. The complete upstream notice is retained in `vendor/THREE-LICENSE.txt`.

- Upstream: https://github.com/mrdoob/three.js/tree/r180
- Download source: https://cdn.jsdelivr.net/npm/three@0.180.0/
- Files: `build/three.module.js`, `build/three.core.js`, and `examples/jsm/controls/OrbitControls.js`.
- `OrbitControls.js` resolves its `three` import using the local import map in `index.html`.
- No external browser requests or runtime CDN dependency are required.

The crystal viewer uses true Cartesian coordinates obtained from the structure's fractional coordinates and lattice matrix. Lines represent distance contacts using covalent-radius heuristics, not calculated bond orders. Atoms exactly on a periodic boundary are also displayed on the matching boundary. No geometry relaxation or dynamics is simulated in the browser.
