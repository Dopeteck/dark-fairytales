# Dark Fairytales — storytelling and pipeline audit

**Reviewed:** 15 November 2026  
**Repository:** `Dopeteck/dark-fairytales`  
**Branch:** `feature/dark-folklore-shorts`  
**Reviewed commit:** `89ef5ab28aa007f7f2d42fcba58791225bf718ce`  
**Status:** Audit only. No renderer, planner, workflow, publishing, or approval behavior is changed by this document.

## Executive assessment

The repository can generate a complete review MP4, but the current implementation is **not yet a production-ready storytelling system**. Its main weakness is architectural, not merely prompt wording: a tale is forced into eight still-image scenes and 180–235 words, then rendered as one generated illustration per scene with a modest Ken Burns move and short crossfades. This tends to compress a story into a plot recap and makes the visuals feel like an illustrated slideshow rather than a directed story.

The latest live run proves both sides of the situation:

- **Successful production work:** the workflow selected *The Goose-Girl*, generated eight 832×1472 images, synthesized one continuous Kokoro narration, and rendered a 78.37-second 1080×1920, 30-fps MP4 with AAC audio and captions.
- **Workflow failure:** after creating the MP4, the runner crashed while building `review-summary.json` because it tried to call `Path.relative_to(ROOT)` on a relative output path and an absolute repository root. The artifact was uploaded despite the failure.

Evidence: [Actions run #43649654561](https://github.com/Dopeteck/dark-fairytales/actions/runs/43649654561).

## What is already working

1. **Source-linked rotation:** `fairytale_queue.json` contains 28 curated tales and source-edition metadata. The rotation logic avoids repeating a completed tale within a cycle.
2. **Basic story constraints:** the planner requires a source edition, synopsis, ordered key beats, recurring characters, scene narration, and character IDs. It prevents empty fields and invalid character references.
3. **A continuous narration pass:** the renderer synthesizes the whole script in one Kokoro pass, rather than restarting the voice at every scene. This is a sound foundation for more natural prosody.
4. **Review-only safety:** generated manifests and render metadata remain unapproved and unpublished. The workflow does not publish or send the MP4. Rotation state advances only after the complete review package passes the runner's checks.
5. **Technical output:** the live run produced a playable portrait MP4, captions, a contact sheet, and metadata. The failed job is therefore not evidence that rendering itself is broken.

## Findings that need attention

### P0 — The post-render path bug makes a successful video look like a failed production

In `fairytale_daily.py`, the output root supplied by the workflow is relative (`output/daily-fairytales`), while `ROOT` is absolute. The summary builder calls `relative_to(ROOT)` on the video, contact-sheet, and captions paths without first resolving both sides to the same path basis. The actual run failed at the contact-sheet path after printing that the MP4 had been created.

**Correction:** normalize both paths with `.resolve()` before calculating repository-relative paths, preferably through one small helper used for all summary paths. Add tests for both relative and absolute `output_root` values. Do not merely suppress the exception: the summary must contain valid, portable paths.

### P0 — The workflow does not validate ordinary feature-branch code changes

The current `push` trigger is restricted to `feature/dark-folklore-shorts`, but its `paths` list contains only `.github/workflows/daily-dark-fairytales.yml`. A commit that changes `fairytale_planner.py`, `fairytale_daily.py`, the scene generator, renderer, queue, or tests will not start this workflow through the push trigger.

The workflow also contains a daily `schedule`, but GitHub scheduled workflows run against the repository's **default branch**, not an unmerged feature branch. The feature-branch schedule is therefore not a valid way to prove daily operation before merge. See [GitHub's workflow syntax documentation](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax).

**Correction:** keep feature-branch end-to-end validation explicit and reliable: use `workflow_dispatch` for controlled provider-backed runs and a branch push trigger that includes the actual pipeline source, tests, queue, and dependency files. Do not merge to `main` just to make a schedule run. Only enable the production schedule after the user separately authorizes the merge.

### P1 — The story is constrained to a synopsis-sized format

`validate_episode_plan()` enforces all of the following:

- exactly eight scenes;
- 16–42 narration words per scene;
- 180–235 words for the entire tale;
- 2–5 recurring characters;
- a fixed 92-second target.

The queue permits 5–10 source key beats, but the validator does not prove that every important beat is represented in the episode, or that the script gives the central conflict, emotional turn, climax, and ending enough space. Eight scenes and a narrow word band are treated as requirements even when the source tale needs a different structure.

The live run's log shows repeated model outputs rejected for scene-count, word-count, title, and character-reference errors before a usable plan was eventually returned. The current JSON correction retry tells the model to return valid JSON, but does not pass the specific validation failure back as actionable feedback.

**Correction:** make episode length and scene count story-led, not fixed. Build a beat map that traces every required source beat to one or more narrative moments. Set a natural target duration and speech-rate range, then allow the writer to use the number of scenes the story actually needs. Add a separate editorial critic that evaluates hook, clarity, stakes, character motivation, escalation, reveal/climax, emotional payoff, and ending before image generation. Return specific validation feedback during bounded repair attempts.

### P1 — The visual system is an illustrated slideshow, not cinematic coverage

For the generic daily fairytale format, `generate_fairytale_scenes.py` creates one 832×1472 still image for each scene. The renderer applies a subtle 8% zoom/pan and 0.38-second crossfades. It does not generate moving footage, multiple camera setups, or cutaway coverage. Character consistency is requested through text descriptions repeated in prompts; the generic format does not use persistent character reference images.

The automated visual checks verify image readability as a file, minimum dimensions, portrait aspect ratio, and non-blank pixels. They do **not** verify that the image depicts the narrated action, that recurring characters retain the same appearance, or that the image is free of malformed lettering. The contact sheet from the live Goose-Girl artifact showed inconsistent character appearance and unwanted malformed text in at least one generated image.

**Correction:** write a shot plan from the approved narrative, not one generic image prompt per paragraph. Use distinct shot sizes, compositions, actions, and cutaways; keep a consistent visual bible and, where supported, reference images for recurring characters. Add a visual-review gate for scene/action relevance, character continuity, obvious text artifacts, anatomy, duplicates, and empty or confusing compositions. Keep human approval for any asset that automated checks cannot confidently assess. Do not represent a still with a zoom effect as generated video footage.

### P1 — Caption timing is estimated, not genuinely word-synchronized

`_story_word_timings_by_scene()` divides the measured narration duration among script words in proportion to their character lengths. That preserves every word and makes the timings add up to the audio duration, but it does not measure when Kokoro actually spoke each word. The tests verify word preservation and timing coverage, not acoustic alignment.

**Correction:** use a genuine forced-alignment or speech-timestamp method compatible with the zero-budget constraint. Until that is implemented and verified, describe the captions as estimated/approximate rather than word-synchronized. Keep the continuous narration pass.

### P1 — There is no independent narrative or visual quality gate

Current validation is primarily structural: JSON shape, text lengths, scene count, character IDs, image file integrity, and render metadata. It does not score whether a tale is captivating, whether a scene earns its place, whether a reveal lands, or whether an illustration actually matches the beat. A model can satisfy the schema and still produce a flat summary or unusable artwork.

**Correction:** add explicit critic stages with structured reasons and bounded retries. A story that fails the editorial threshold should stop before image generation. A visually weak scene should be regenerated or flagged for human review, not silently accepted because its dimensions are valid.

### P2 — The queue is currently a narrow Western-European collection

The 28 entries are drawn from Grimm (17 entries across two collection titles), Perrault (4), and Andersen (7). That is a coherent starting library, but it is not yet a broad international folklore catalogue. This is a content strategy issue, not a reason to delay the core storytelling rebuild.

**Correction:** after the story pipeline is reliable, expand the queue with carefully sourced tales from additional oral and literary traditions. Preserve edition/variant provenance and avoid blending different versions into one retelling without disclosure.

### P2 — The daily runner tests do not cover the failure that happened

The runner's unit tests mock image generation and rendering. They verify that rotation state is written after success and not written after a render failure, but they do not exercise the real relative-output-path summary case that failed in Actions. The live workflow is the only end-to-end proof currently available, and its first real run failed after rendering.

**Correction:** add regression tests for the real path shapes and require a successful branch-dispatched run that produces and uploads a review artifact before calling the pipeline reliable.

## Recommended rebuild sequence

1. **Restore trustworthy validation first:** fix path normalization; fix feature-branch workflow triggers; add regression tests; retain artifact upload on failure so partial outputs remain inspectable.
2. **Rebuild the story engine:** variable scene count and runtime; source-beat coverage; a stronger dramatic arc; natural dialogue and spoken rhythm; an independent critic; actionable repair feedback.
3. **Rebuild visual direction and QA:** shot-level coverage, recurring character consistency, scene/action matching, rejection of text artifacts and obvious visual defects, and explicit human-review flags.
4. **Improve narration and captions:** preserve one continuous Kokoro performance; judge pacing by listening to the rendered artifact; derive caption timestamps from speech alignment rather than proportional word lengths.
5. **Prove repeatability:** complete at least three end-to-end review runs using substantially different tales. Review the actual MP4, narration, captions, and contact sheet—not just unit-test output or a successful FFmpeg exit code.

## Production-readiness acceptance criteria

Do not call the pipeline ready for daily production until:

- a code change on the feature branch reliably triggers the intended validation;
- the full runner exits successfully and produces a complete review package;
- different tales are not forced into the same scene count or word count;
- every essential source beat has an explicit place in the retelling;
- the story passes a measurable editorial review before images are generated;
- generated images visibly match their scene actions and recurring character designs;
- obvious text artifacts and broken imagery are rejected or flagged;
- narration is listened to and judged for natural pacing, emphasis, and emotional delivery;
- caption timing is verified against the spoken audio;
- artifacts remain private review material until a human explicitly approves them;
- no automatic publishing, Telegram delivery, or merge to `main` occurs without separate approval.

**Bottom line:** fixing the path exception alone will make the run turn green, but it will not fix the product. The next meaningful work is a controlled rebuild of the story, shot-planning, and quality-review stages, with the workflow reliability defects fixed first.
