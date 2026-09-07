# FlashPilot model selector

This port adds SunnyPilot's downloadable model catalog to the original openpilot-based FlashPilot line.

## Runtime contract

- With no verified custom bundle selected, FlashPilot runs its existing stock `modeld` and stock model unchanged.
- The offroad model manager downloads chunked artifacts into `Paths.model_root()`, verifies every chunk hash, and only then records the bundle as active.
- A verified bundle whose catalog runner is `tinygrad` selects `sunnypilot/modeld_v2` on the next onroad transition.
- Removing the active bundle returns process selection to stock `modeld`.
- A failed, cancelled, incomplete, or corrupt download cannot replace the active bundle.
- The Chestnut catalog path is intentionally disabled in this port. FlashPilot's existing stock Chestnut support remains independent.

## User interface

Comma 4 Settings includes a top-level **models** page. Model selection and downloads are available offroad. The page displays the active model, catalog folders, favorites, download progress, and a cancel action.

## Compatibility

The selector consumes SunnyPilot's `driving_models_v22.json` schema at selector version 19. `tinygrad_repo` must remain pinned to the `tinygrad_ref` published by that manifest.

FlashPilot also adds one immutable local catalog overlay: **RDF V4 (StarPilot)**. It references StarPilot commit `f55ad9162d77993a7e558ad6c2507a94b55132a9`, downloads three QCOM chunks, and verifies their published hashes before activation. It is never downloaded or selected automatically and does not replace the stock default.
