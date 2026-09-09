# Clear Air: withdraw RDF V4

RDF V4 is removed from the selectable/downloadable catalog. Its retired ref,
artifact hash and filename are excluded when reading current or cached catalogs
and saved selections, so an old cache cannot restore it. A saved RDF runner cache
falls back through the existing stock model selection. Other models remain available.

There were no RDF-only Params or UI controls. Generic model settings, the catalog
manager/downloader, alternate runner and parsers remain because other models use
them. In particular, the 144-value lead layout also belongs to CD210-family models;
its shared parsing logic and regression coverage must remain.

The later RDF tuple/startup/delay compatibility experiments were never integrated
into this baseline. They are excluded from this change and retained as investigation
history, not promoted into production. Earlier RDF-family fixtures that still protect
shared parsing are not dead tests. Obsolete V4 catalog-injection assertions are removed.

Current CD210/native model source, inference, postprocessing, Params, camera transport
and publications are unchanged. No lateral, longitudinal, radar, AOL, safety or
unrelated UI source is changed. No model files or vehicle state are deleted here.

Investigation records remain in the workspace's `work/rdf-hardware-validation/`
and `coordination/lightning/`, including the exact-artifact audit and failed hardware
gate. Existing Git history is preserved. This commit withdraws the model; it does
not assert that another model was tested, tuned or improved.
