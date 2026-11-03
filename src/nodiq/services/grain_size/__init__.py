"""Steel grain-size analysis engines (independent of the Cast Iron
Graphite Nodularity product).

This package only *adapts* the two bundled third-party repositories:

* ``gsat_adapter``          — the real GSAT implementation
                              (``grain-size-analysis-tools-main/``, NIST)
* ``astm_estimator_adapter`` — the real ASTM Grain-Size Estimator inference +
                              Jeffries planimetric code
                              (``ASTM-Grain-Size-Estimator-main/``)
* ``service``               — orchestration: runs the selected pipeline(s) on
                              one image and returns structured results; it
                              never fabricates measurements.

The adapters invoke the original repositories' functions rather than
re-implementing their algorithms.
"""
