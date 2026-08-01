# Security and Data Policy

This repository is a synthetic-data-only technical portfolio project.

- It does not contain real experimental matrices, images, measurements, sample identifiers, laboratory documents, or experiment logs.
- Every file under `demo/synthetic_series/` is generated deterministically and is not derived from scientific source data.
- Original scientific data must remain outside this repository and must never be committed, attached to issues, or added to pull requests.
- User-generated run directories, local environments, local configuration overrides, caches, and logs are excluded by `.gitignore`.
- Configuration committed as an example must use portable relative paths and synthetic inputs only.
- The physical interpretation and scientific accuracy of the detector must be validated against expert annotation or an independent method.

Before committing new data or screenshots, verify that they contain no personal identifiers, organization names, absolute local paths, credentials, or real experimental metadata.

