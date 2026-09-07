"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""

import asyncio
import os
import time

import aiohttp
from openpilot.common.params import Params
from openpilot.common.realtime import Ratekeeper
from openpilot.common.swaglog import cloudlog
from openpilot.common.hardware.hw import Paths

from openpilot.cereal import messaging, custom
from openpilot.sunnypilot.models.fetcher import ModelFetcher
# BluePilot: deviceState has no chestnutPresent on this base; the gated USB GPU probe in helpers is used instead
from openpilot.sunnypilot.models.helpers import (ACTIVE_BUNDLE_KEYS, chestnut_present, get_active_bundle, get_selected_bundle,
                                                  resolve_bundle_by_ref, validate_active_bundles, verify_file)
# End BluePilot


class DownloadCancelled(Exception):
  pass


class ModelManagerSP:
  """Manages model downloads and status reporting"""

  def __init__(self):
    self.params = Params()
    self.model_fetcher = ModelFetcher(self.params)
    self.pm = messaging.PubMaster(["modelManagerSP"])
    self.chestnut_present = chestnut_present()  # BluePilot: sysfs probe instead of deviceState
    self.available_models: list[custom.ModelManagerSP.ModelBundle] = []
    self.source_models: dict[str, list[custom.ModelManagerSP.ModelBundle]] = {}
    self.selected_bundle: custom.ModelManagerSP.ModelBundle = None
    self.active_bundle: custom.ModelManagerSP.ModelBundle = get_active_bundle(self.params, chestnut=self.chestnut_present)
    self._chunk_size = 128 * 1000  # 128 KB chunks
    self._download_start_times: dict[str, float] = {}  # Track start time per model
    self._download_ref: bytes | str | None = None

  def _download_interrupted(self) -> bool:
    # only removal cancels: a different ref is a queued selection that
    # _release_download_ref leaves in place for the next tick
    return self.params.get("ModelManager_DownloadRef") is None

  def _release_download_ref(self) -> None:
    if self.params.get("ModelManager_DownloadRef") == self._download_ref:
      self.params.remove("ModelManager_DownloadRef")
    self._download_ref = None

  def _sync_artifact_progress(self, source_artifact) -> None:
    """Mirror download progress to all artifacts sharing the same filename in the selected bundle."""
    if not self.selected_bundle:
      return
    for model in self.selected_bundle.models:
      artifact = model.artifact
      if artifact is not source_artifact and artifact.fileName == source_artifact.fileName:
        artifact.downloadProgress.status = source_artifact.downloadProgress.status
        artifact.downloadProgress.progress = source_artifact.downloadProgress.progress
        artifact.downloadProgress.eta = source_artifact.downloadProgress.eta

  def _calculate_eta(self, filename: str, progress: float) -> int:
    """Calculate ETA based on elapsed time and current progress"""
    if filename not in self._download_start_times or progress <= 0:
      return 60  # Default ETA for new downloads

    elapsed_time = time.monotonic() - self._download_start_times[filename]
    if elapsed_time <= 0:
      return 60

    # If we're at X% after Y seconds, we can estimate total time as (Y / X) * 100
    total_estimated_time = (elapsed_time / progress) * 100
    eta = total_estimated_time - elapsed_time

    return max(1, int(eta))  # Return at least 1 second if download is ongoing

  async def _download_file(self, url: str, path: str, model) -> None:
    """Downloads a file with progress tracking"""
    self._download_start_times[model.fileName] = time.monotonic()

    async with aiohttp.ClientSession() as session:
      async with session.get(url) as response:
        response.raise_for_status()
        total_size = int(response.headers.get("content-length", 0))
        bytes_downloaded = 0

        with open(path, 'wb') as f:
          async for chunk in response.content.iter_chunked(self._chunk_size):  # type: bytes
            f.write(chunk)
            bytes_downloaded += len(chunk)

            if self._download_interrupted():
              raise DownloadCancelled("Download cancelled")

            if total_size > 0:
              progress = (bytes_downloaded / total_size) * 100
              model.downloadProgress.status = custom.ModelManagerSP.DownloadStatus.downloading
              model.downloadProgress.progress = progress
              model.downloadProgress.eta = self._calculate_eta(model.fileName, progress)
              self._sync_artifact_progress(model)
              self._report_status()

        # Clean up start time after download completes
        del self._download_start_times[model.fileName]


  async def _download_chunked(self, base_url: str, base_path: str, artifact) -> None:
    # BluePilot: selector v19 declares chunks in the catalog; keep the existing aiohttp transport.
    from openpilot.common.file_chunker import get_chunk_name
    num_chunks = len(artifact.chunks)
    if num_chunks == 0:
      raise ValueError("No chunks defined in artifact")
    # End BluePilot

    self._download_start_times[artifact.fileName] = time.monotonic()

    for i in range(num_chunks):
      chunk_url = get_chunk_name(base_url, i, num_chunks)
      chunk_path = get_chunk_name(base_path, i, num_chunks)
      chunk_downloaded = 0
      async with aiohttp.ClientSession() as session:
        async with session.get(chunk_url) as response:
          response.raise_for_status()
          chunk_size = int(response.headers.get("content-length", 0))
          with open(chunk_path, 'wb') as f:
            async for data in response.content.iter_chunked(self._chunk_size):
              f.write(data)
              chunk_downloaded += len(data)
              if self._download_interrupted():
                raise DownloadCancelled("Download cancelled")
              intra = chunk_downloaded / max(chunk_size, 1)
              progress = min(99, (i + intra) / num_chunks * 100)
              artifact.downloadProgress.status = custom.ModelManagerSP.DownloadStatus.downloading
              artifact.downloadProgress.progress = progress
              artifact.downloadProgress.eta = self._calculate_eta(artifact.fileName, progress)
              self._sync_artifact_progress(artifact)
              self._report_status()

    del self._download_start_times[artifact.fileName]


  async def _process_artifact(self, artifact, destination_path: str) -> None:
    # BluePilot: support catalog-declared chunk hashes without porting retry/resume behavior.
    from openpilot.common.file_chunker import get_chunk_name, get_manifest_path
    if not artifact.downloadUri.uri:
      raise ValueError("Model artifact has no download URL")

    filename = artifact.fileName
    full_path = os.path.join(destination_path, filename)
    chunked = bool(len(artifact.chunks))
    files = ([(get_chunk_name(full_path, i, len(artifact.chunks)), chunk.sha256)
              for i, chunk in enumerate(artifact.chunks)] if chunked else [(full_path, artifact.downloadUri.sha256)])

    async def verified() -> bool:
      for path, expected_hash in files:
        if self._download_interrupted():
          raise DownloadCancelled("Download cancelled")
        if not expected_hash or not await verify_file(path, expected_hash):
          return False
      return True

    if self._download_interrupted():
      raise DownloadCancelled("Download cancelled")
    download_started = False
    try:
      is_cached = await verified()
      if not is_cached:
        download_started = True
        if chunked:
          await self._download_chunked(artifact.downloadUri.uri, full_path, artifact)
        else:
          await self._download_file(artifact.downloadUri.uri, full_path, artifact)
        artifact.downloadProgress.status = custom.ModelManagerSP.DownloadStatus.verifying
        self._sync_artifact_progress(artifact)
        self._report_status()
        if not await verified():
          raise ValueError(f"Hash validation failed for {filename}")

      # Publish a manifest only after every declared chunk is verified. Parsing a catalog is read-only.
      if chunked:
        with open(get_manifest_path(full_path), 'w') as manifest:
          manifest.write(str(len(artifact.chunks)))
        if os.path.isfile(full_path):
          os.remove(full_path)
      elif os.path.isfile(get_manifest_path(full_path)):
        os.remove(get_manifest_path(full_path))
      artifact.downloadProgress.status = (custom.ModelManagerSP.DownloadStatus.cached if is_cached
                                         else custom.ModelManagerSP.DownloadStatus.downloaded)
      artifact.downloadProgress.progress = 100
      artifact.downloadProgress.eta = 0
      self._sync_artifact_progress(artifact)
      self._report_status()
    except Exception as e:
      cloudlog.error(f"Error downloading {filename}: {e}")
      # Discard failed downloads; cancellation while inspecting the cache must not erase an active model.
      if download_started:
        for path in {full_path, get_manifest_path(full_path), *(path for path, _ in files)}:
          if os.path.isfile(path):
            os.remove(path)
      artifact.downloadProgress.status = custom.ModelManagerSP.DownloadStatus.failed
      artifact.downloadProgress.eta = 0
      self._sync_artifact_progress(artifact)
      if self.selected_bundle is not None:
        self.selected_bundle.status = custom.ModelManagerSP.DownloadStatus.failed
      self._report_status()
      raise
    finally:
      self._download_start_times.pop(filename, None)
    # End BluePilot

    # End BluePilot

  async def _process_model(self, model, destination_path: str) -> None:
    """Processes a single model download including verification"""
    await self._process_artifact(model.artifact, destination_path)

  def _report_status(self) -> None:
    """Reports current status through messaging system"""
    msg = messaging.new_message('modelManagerSP', valid=True)
    model_manager_state = msg.modelManagerSP
    if self.selected_bundle:
      model_manager_state.selectedBundle = self.selected_bundle

    if self.active_bundle:
      model_manager_state.activeBundle = self.active_bundle

    model_manager_state.availableBundles = self.available_models
    self.pm.send('modelManagerSP', msg)

  async def _download_bundle(self, model_bundle: custom.ModelManagerSP.ModelBundle, destination_path: str, source: str) -> None:
    self.selected_bundle = model_bundle
    self.selected_bundle.status = custom.ModelManagerSP.DownloadStatus.downloading
    for model in self.selected_bundle.models:
      model.artifact.downloadProgress.status = custom.ModelManagerSP.DownloadStatus.downloading
    self._report_status()
    os.makedirs(destination_path, exist_ok=True)

    try:
      seen_artifacts: set[str] = set()
      for model in self.selected_bundle.models:
        artifact = model.artifact
        if not artifact.fileName:
          continue
        if artifact.fileName in seen_artifacts:
          artifact.downloadProgress.status = custom.ModelManagerSP.DownloadStatus.cached
          artifact.downloadProgress.progress = 100
          artifact.downloadProgress.eta = 0
        else:
          seen_artifacts.add(artifact.fileName)
          await self._process_artifact(artifact, destination_path)

      if self._download_interrupted():
        raise DownloadCancelled("Download cancelled")
      self.selected_bundle.status = custom.ModelManagerSP.DownloadStatus.downloaded
      self.params.put(ACTIVE_BUNDLE_KEYS[source], model_bundle.to_dict(), block=True)
      self.active_bundle = get_active_bundle(self.params, chestnut=self.chestnut_present)

    except Exception:
      if self.selected_bundle is not None:
        self.selected_bundle.status = custom.ModelManagerSP.DownloadStatus.failed
      raise

    finally:
      self._report_status()

  def download(self, model_bundle: custom.ModelManagerSP.ModelBundle, destination_path: str, source: str) -> None:
    """Main entry point for downloading a model bundle"""
    asyncio.run(self._download_bundle(model_bundle, destination_path, source))

  def _process_download_requests(self) -> None:
    # loops so a ref queued during a download starts in the same tick, without
    # the bar dropping to idle for a tick between the two transfers
    last_ref = None
    while (ref_to_download := self.params.get("ModelManager_DownloadRef")) is not None:
      if ref_to_download == last_ref:  # a repeating ref falls back to the next tick instead of spinning
        return
      last_ref = ref_to_download
      source = ModelFetcher.active_source(self.chestnut_present)
      resolved = resolve_bundle_by_ref(ref_to_download, {source: self.source_models.get(source, [])})
      if not resolved:
        return
      model_to_download, source = resolved
      self._download_ref = ref_to_download
      try:
        self.download(model_to_download, Paths.model_root(), source)
      # BluePilot: cancellation clears the selection; failures remain visible until another request.
      except DownloadCancelled:
        self.selected_bundle = None
      except Exception as e:
        cloudlog.exception(e)
      else:
        self.selected_bundle = None
      finally:
        self._release_download_ref()
      # End BluePilot

  def main_thread(self) -> None:
    """Main thread for model management"""
    rk = Ratekeeper(1, print_delay_threshold=None)

    while True:
      try:
        self.chestnut_present = chestnut_present()  # BluePilot: sysfs probe instead of deviceState
        self.source_models = {source: self.model_fetcher.get_bundles_for_source(source) for source in ModelFetcher.MODEL_SOURCES}
        self.available_models = self.source_models[ModelFetcher.active_source(self.chestnut_present)]
        validate_active_bundles(self.params, self.source_models)
        self.active_bundle = get_active_bundle(self.params, chestnut=self.chestnut_present)

        self._process_download_requests()

        if self.params.get("ModelManager_ClearCache"):
          self.clear_model_cache()
          self.params.remove("ModelManager_ClearCache")

        self._report_status()
        rk.keep_time()

      except Exception as e:
        cloudlog.exception(f"Error in main thread: {str(e)}")
        rk.keep_time()

  def clear_model_cache(self) -> None:
    """
    Clears the model cache directory of all files except those in the active model bundle.
    """

    # Get list of files used by both slots' selected bundles (either may become
    # the truly active bundle depending on hardware availability)
    active_files = []
    for source in ACTIVE_BUNDLE_KEYS:
      if selected_bundle := get_selected_bundle(self.params, source):
        for model in selected_bundle.models:
          if model.artifact.fileName:
            active_files.append(model.artifact.fileName)

    # Remove all files except active ones (including their chunk files)
    model_dir = Paths.model_root()
    try:
      for filename in os.listdir(model_dir):
        base = filename.split('.chunk')[0] if '.chunk' in filename else filename
        if base not in active_files and filename not in active_files:
          file_path = os.path.join(model_dir, filename)
          if os.path.isfile(file_path):
            os.remove(file_path)
      cloudlog.info("Model cache cleared, keeping active model files")
    except Exception as e:
      cloudlog.exception(f"Error clearing model cache: {str(e)}")

def main():
  ModelManagerSP().main_thread()


if __name__ == "__main__":
  main()
