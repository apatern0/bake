# Copyright 2025 CERN
# Copyright 2026 Andrea Paterno'
# SPDX-License-Identifier: Apache-2.0
#
# This file is a modified version of a file from tmake
# (https://gitlab.cern.ch/tmake/tmake), developed at CERN and
# distributed under the Apache License, Version 2.0.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Exception classes for errors caught during runtime of bake"""

class BakeRuntimeError(Exception):
    """Base class that can be used to catch all bake-generated exceptions."""
    pass

class BakeInternalError(BakeRuntimeError):
    """Exception for internal consistency failures that should never occur."""
    pass

class BakeIncludeError(BakeRuntimeError):
    """Exception used to signal non-existing targets to include."""
    pass

class BakeFileError(BakeRuntimeError):
    """Exception used to signal non-existing files or directories."""
    pass

class BakeManifestError(BakeRuntimeError):
    """Exception raised when logical/semantic errors exist in the manifest."""
    pass

class BakeConfigError(BakeRuntimeError):
    """Exception to indicate errors with bake configuration."""
    pass

class BakeUserRuntimeError(BakeRuntimeError):
    """Exception that can be raised from user manifest code for error handling."""
    pass

class BakeStepExecutionError(BakeRuntimeError):
    """Exception raised when a flow step exits with a non-zero return code."""
    pass
