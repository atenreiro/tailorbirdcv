"""Hatch build hook: ship the built web UI inside the wheel, so users don't need Node.

`npm --prefix web ci && npm --prefix web run build` must run before `uv build` (the release
workflow does). Editable/dev installs serve web/dist straight from the checkout instead.
"""

from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version, build_data):
        if self.target_name != "wheel" or version == "editable":
            return
        dist = Path(self.root) / "web" / "dist"
        if not (dist / "index.html").is_file():
            raise RuntimeError("web/dist is missing: run `npm --prefix web ci && npm --prefix web run build` first")
        build_data["force_include"][str(dist)] = "autocv/web"
