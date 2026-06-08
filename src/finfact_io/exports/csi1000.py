from __future__ import annotations

from finfact_io.exports.index_point_in_time import (
    AsofPolicy,
    CSI1000_SPEC,
    IndexPointInTimeBuildReport,
    build_csi1000_dataset,
)

CSI1000_INDEX_CODE = CSI1000_SPEC.index_code
CSI1000_INDEX_NAME = CSI1000_SPEC.index_name
CSI1000_TOTAL_RETURN_CODE = CSI1000_SPEC.total_return_candidates[0]
DEFAULT_OUTPUT_DIR = CSI1000_SPEC.default_output_dir

Csi1000BuildReport = IndexPointInTimeBuildReport

__all__ = [
    "AsofPolicy",
    "CSI1000_INDEX_CODE",
    "CSI1000_INDEX_NAME",
    "CSI1000_TOTAL_RETURN_CODE",
    "DEFAULT_OUTPUT_DIR",
    "Csi1000BuildReport",
    "build_csi1000_dataset",
]
