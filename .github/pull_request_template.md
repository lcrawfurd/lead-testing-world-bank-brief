# Summary

<!-- One or two sentences. What does this change? -->

## Motivation

<!-- Why? Link to an issue if relevant. -->

## Pipeline impact

- [ ] No change to pipeline outputs (docs, README, comments only)
- [ ] Changes pipeline outputs — `make verify` still passes
- [ ] Changes pipeline outputs and expected ranges in `verify_pipeline.py` updated

## Checklist

- [ ] `make audit && make enrich && make chart && make verify` passes locally
- [ ] No PII, secrets, or large files added
- [ ] README still accurate
