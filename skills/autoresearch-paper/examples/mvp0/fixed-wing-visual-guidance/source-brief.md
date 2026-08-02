# P1 acceptance source brief

- Codex task: `019fb6a0-a1cc-7422-ae35-8e9625de1c13`
- Research workspace: `/Users/wdblink/Research/papers/Fixed-Win-Visual-Guidance`
- Experiment code: `/Users/wdblink/Code/my_repo/pyflyt-drone`

The initial research goal was to train a fixed-wing target-approach policy with
privileged information while deploying from onboard vision and vehicle state
only, then quantify degradation and safety under wind, occlusion, obstacles,
and a real detector. The existing Actor observation includes the true relative
target vector, so the current policy is not a pure-vision baseline. The legacy
truth and FastSAM evaluators also differ in more than the detector. No existing
trained model, batch result, or SOTA claim is assumed by this acceptance case.

P1 compiles that goal only. It does not run training, authorize a Worker, or
claim scientific success.
