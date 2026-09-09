from tempfile import TemporaryDirectory

import pytest

from openpilot.common.params import Params, UnknownKeyName
from openpilot.sunnypilot.livedelay.helpers import get_lat_delay


def test_published_delay_without_obsolete_toggle():
  with TemporaryDirectory() as directory:
    params = Params(directory)
    with pytest.raises(UnknownKeyName):
      params.check_key("LagdToggle")
    params.put("LagdValueCache", 0.2, block=True)
    for published_delay in (0.0, 0.27, 0.65):
      assert get_lat_delay(params, published_delay) == published_delay
