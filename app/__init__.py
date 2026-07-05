# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Pocket CFO application package.

Re-exports the deployable ADK `app` (assembled in app/agent.py) so that
`google-agents-cli` and the FastAPI server can discover it as `app.app`. All real
agent wiring lives in app/agent.py; this package root is intentionally thin.
"""

from .agent import app

__all__ = ["app"]
