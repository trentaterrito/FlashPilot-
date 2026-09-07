"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""

from openpilot.sunnypilot import get_file_hash
from openpilot.sunnypilot.models.default_model import DEFAULT_ONNX_PATH, MODEL_HASH_PATH


class TestDefaultModel:
  def test_compare_onnx_hashes(self):
    combined_hash = get_file_hash(DEFAULT_ONNX_PATH)

    with open(MODEL_HASH_PATH) as f:
      current_hash = f.read().strip()

    assert combined_hash == current_hash, "Run sunnypilot/models/default_model.py to update the default model name and hash"
