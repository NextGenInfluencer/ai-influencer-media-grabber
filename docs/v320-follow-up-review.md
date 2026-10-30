# v3.2.0 focused follow-up review — 2026-10-30

Reviewed the clean checkout at `8b98a0c`, release changes, installer/browser evidence, and saved preview/export images. The published release was not changed. Corrections are versioned 3.2.1; the user subsequently authorized publication.

## Findings corrected locally

- **Ollama privacy:** A localhost address does not ensure local inference. Model discovery accepted cloud aliases, contradicting the local-only translation promise. Discovery now excludes remote metadata; every generation first checks `/api/show` without lyric content, rejects remote or unverifiable metadata, and refuses HTTP redirects. Regression tests cover remote aliases, missing metadata, failures, and downloaded local models. This assumes an honest local Ollama daemon, not a malicious replacement. Official API fields: https://github.com/ollama/ollama/blob/main/api/types.go ; cloud behavior: https://docs.ollama.com/cloud .
- **Greek/Korean timing review:** Mixed-script detection previously required Latin letters and missed Greek/Korean lines in auto-language mode. Both refinement paths now use shared detection covering these script pairs, including accented Latin characters. This flags uncertainty; it does not make forced alignment more accurate.
- **Evidence/documentation:** The installer acceptance report identifies a pre-publication binary (116,432,366 bytes), while the user handoff identifies a different final binary (116,446,365 bytes). The completion document now distinguishes these builds and removes stale publication-approval wording. Fixed control characters in the changelog.

## Verification boundaries

- Baseline full suite independently passed: 160 tests in 64.216 seconds.
- Final full suite after corrections passed: 165 tests in 62.252 seconds (`audit_artifacts/codex-v321-regression.log`). Whitespace checks passed.
- Targeted follow-up checks passed in both development Python and clean embedded Python 3.13: 25 tests each. JavaScript timing/draft tests and syntax checks passed.
- Saved browser/export artifacts show multilingual text and highlighting, but do not establish pixel-identical rendering. Text outlines/background metrics visibly differ; the existing five-second rendered check remains the reliable export reference.
- Generated song timing reports and review guides are not proof of a completed human listening review. The nine flagged lines remain listening-review work for the song owner.
- No live Ollama daemon, new model download, new installer build, or installed-user-app upgrade was performed in this follow-up. Existing user projects/media were not edited.
- The final published installer has not been independently downloaded or compared byte-for-byte against the earlier acceptance build in this review.
