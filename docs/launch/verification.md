# Launch-film verification

The final current-source film was rendered with the pinned local HyperFrames 0.8.33 runner,
standard quality and one worker. The application captures were refreshed after aligning
API/CLI initialization with the frozen benchmark's row ordering. Input hashes are retained
in `sources.json`; quantitative plot pixels come directly from the real experiment figure.

- 20.000 seconds, 1920×1080, 30 fps, 600 video frames; H.264 video and AAC audio.
- Full FFmpeg decode completed without errors.
- Lint and runtime checks passed with zero errors and warnings.
- Nine layout samples passed with no errors or warnings. Eight informational detections
  describe intentional brief crossfade overlap/occlusion. Settled screenshots and actual
  encoded frames at the candidate, reference-update and benchmark scenes were inspected.
- Contrast checks passed all 27 tested text instances. The pinned runner's motion-audit
  module is disabled; a motion-audit pass is not claimed.
- The selected poster is actual frame 5.6 seconds, showing the working application. It is
  baked into frame zero. Compression-aware image comparison verifies the first frame.
- The quiet score is original deterministic synthesis, with no voice cloning or narration.
  Encoded volume measurements are recorded in `verification.json`; no clipping was observed.
  Metering does not establish a subjective independent listening assessment.

The film presents actual interface states and saved retrospective measurements. The camera
motion, transitions and score are presentation, not physical calculations. It makes no claim
of new DFT, synthesis, or independent pretrained-model generalization.
