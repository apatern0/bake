# Copyright 2026 Andrea Paterno'
# SPDX-License-Identifier: Apache-2.0
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

"""The processes a step's flow starts, tracked so that bake reaches all of them.

A flow's tools do not stay in the process group bake starts them in: a
simulator opens its GUI in a session of its own, a server daemonizes.  A
tracker knows every process of a step, wherever it went, so that an
interrupt of bake is passed on to all of them and none outlives the step.

Mechanisms, as `track()` tries them (`config.bake.process_tracking`):

- `cgroup`: the step runs in a cgroup v2 of its own, a child of bake's own
  cgroup when that is writable (a delegated subtree), or a systemd user scope
  otherwise.  Nothing leaves a cgroup; a cgroup left by a killed bake is
  cleaned up by the next one.
- `subreaper`: bake is the child subreaper of the step's processes, so that
  those that daemonize are re-parented to bake rather than to init, and
  remain its descendants.  A bake killed with SIGKILL leaves them running.
- `group`: the step's process group only, as bake did before (not tried by
  `auto`).
"""

import ctypes
import itertools
import logging
import os
from pathlib import Path
import shlex
import shutil
import signal
import subprocess
import time

from . import exceptions
from .context import context

CGROUP_ROOT = Path("/sys/fs/cgroup")
MECHANISMS = ("auto", "cgroup", "subreaper", "group")

PR_SET_CHILD_SUBREAPER = 36
PR_GET_CHILD_SUBREAPER = 37

_steps = itertools.count(1)   # numbers the cgroups and scopes of this bake


# ---------------------------------------------------------------------------
# /proc
# ---------------------------------------------------------------------------

def _stat(pid):
    """(ppid, pgrp, state, start time in clock ticks since boot) of a
    process; None when it does not exist."""
    try:
        text = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    fields = text[text.rindex(")") + 2:].split()
    return int(fields[1]), int(fields[2]), fields[0], int(fields[19])


def _processes():
    """{pid: _stat(pid)} of every process."""
    found = {}
    for entry in os.scandir("/proc"):
        if entry.name.isdigit():
            st = _stat(entry.name)
            if st is not None:
                found[int(entry.name)] = st
    return found


def _alive(pid):
    st = _stat(pid)
    return st is not None and st[2] != "Z"


def _now_ticks():
    return int(time.clock_gettime(time.CLOCK_BOOTTIME) * os.sysconf("SC_CLK_TCK"))


def describe(pid):
    """A process's command line, for the log."""
    try:
        cmd = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace").strip()
    except OSError:
        cmd = ""
    if not cmd:
        try:
            cmd = "[" + Path(f"/proc/{pid}/comm").read_text(encoding="utf-8").strip() + "]"
        except OSError:
            cmd = "?"
    return cmd if len(cmd) <= 160 else cmd[:157] + "..."


def _kill(pid, signum):
    try:
        os.kill(pid, signum)
        return True
    except (ProcessLookupError, PermissionError):
        return False


# ---------------------------------------------------------------------------
# Trackers
# ---------------------------------------------------------------------------

class Tracker:
    """The processes of one step.  Start the step's command with `command()`,
    `preexec` and `popen_kwargs`, then call `started()` with its Popen."""

    mechanism = ""

    def __init__(self):
        self.proc = None
        self.interrupts = 0
        self.signal_name = None     # the first interrupt received, if any
        self.preexec = None

    @property
    def where(self):
        """Where the processes are tracked, for the log."""
        return self.mechanism

    def command(self, cmd):
        return cmd

    def started(self, proc):
        self.proc = proc

    def pids(self):
        """The step's live processes."""
        raise NotImplementedError

    def send(self, signum):
        """Send a signal to every process of the step; the number reached."""
        return sum(_kill(pid, signum) for pid in self.pids())

    def kill(self):
        return self.send(signal.SIGKILL)

    def poll(self):
        """Housekeeping while the step runs."""

    def interrupt(self, signum):
        """bake received `signum`: pass the first on, kill at the second."""
        name = signal.Signals(signum).name
        self.interrupts += 1
        if self.interrupts == 1:
            self.signal_name = name
            reached = self.send(signum)
            logging.info("Received %s, forwarding it to %d flow processes (%s); interrupt again to kill them.",
                         name, reached, self.where)
        else:
            reached = self.kill()
            logging.info("Received %s again, killing %d flow processes.", name, reached)

    def end(self, grace):
        """The step's script has exited: end the processes it left, SIGTERM
        first, SIGKILL those still running `grace` seconds later."""
        survivors = sorted(self.pids())
        if not survivors:
            return
        level = logging.INFO if self.interrupts else logging.WARNING
        logging.log(level, "The flow left %d processes running (%s); ending them:", len(survivors), self.where)
        for pid in survivors:
            logging.log(level, "   %7d  %s", pid, describe(pid))
        self.send(signal.SIGTERM)
        if not self._wait_empty(grace):
            logging.log(level, "   %d still running after %g s; killing them.", len(self.pids()), grace)
            self.kill()
            if not self._wait_empty(5):
                logging.warning("   Could not end: %s", ", ".join(str(p) for p in sorted(self.pids())))

    def _wait_empty(self, seconds):
        deadline = time.monotonic() + seconds
        while True:
            self.poll()
            if not self.pids():
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.1)

    def close(self):
        """Undo what the tracker set up; the step is over."""


class GroupTracker(Tracker):
    """The step's process group, which the step's command leads."""

    mechanism = "group"

    def pids(self):
        if self.proc is None:
            return set()
        return {pid for pid, (_, pgrp, state, _) in _processes().items()
                if pgrp == self.proc.pid and state != "Z"}

    def send(self, signum):
        if self.proc is None:
            return 0
        reached = len(self.pids())
        try:
            os.killpg(self.proc.pid, signum)
        except (ProcessLookupError, PermissionError):
            return 0
        return reached

    def end(self, grace):
        """What left the group is out of reach, and what stayed is left
        alone: the behaviour of bake before trackers."""


class SubreaperTracker(Tracker):
    """bake's descendants started since the step began, bake being their
    child subreaper so that none can leave its tree."""

    mechanism = "subreaper"

    def __init__(self):
        super().__init__()
        self._libc = ctypes.CDLL(None, use_errno=True)
        previous = ctypes.c_int(0)
        if self._libc.prctl(PR_GET_CHILD_SUBREAPER, ctypes.byref(previous), 0, 0, 0) != 0:
            raise OSError(ctypes.get_errno(), "prctl(PR_GET_CHILD_SUBREAPER) failed")
        self._previous = previous.value
        if self._libc.prctl(PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0) != 0:
            raise OSError(ctypes.get_errno(), "prctl(PR_SET_CHILD_SUBREAPER) failed")
        # One tick of slack: a start time is rounded down to a tick.
        self._since = _now_ticks() - 1

    def _tree(self):
        """{pid: state} of bake's descendants started since the step began.
        Older children of bake's (a test runner's) are not the step's."""
        procs = _processes()
        children = {}
        for pid, (ppid, _, _, start) in procs.items():
            if start >= self._since:
                children.setdefault(ppid, []).append(pid)
        tree, todo = {}, list(children.get(os.getpid(), []))
        while todo:
            pid = todo.pop()
            tree[pid] = procs[pid][2]
            todo.extend(children.get(pid, []))
        return tree

    def pids(self):
        return {pid for pid, state in self._tree().items() if state != "Z"}

    def poll(self):
        """Reap the adopted processes that exited: they are bake's children
        now.  Only those, by pid: the step's own command is Popen's."""
        own = self.proc.pid if self.proc is not None else None
        for pid, (ppid, _, state, start) in _processes().items():
            if ppid == os.getpid() and state == "Z" and pid != own and start >= self._since:
                try:
                    os.waitpid(pid, os.WNOHANG)
                except ChildProcessError:
                    pass

    def close(self):
        self.poll()
        self._libc.prctl(PR_SET_CHILD_SUBREAPER, self._previous, 0, 0, 0)


class CgroupTracker(Tracker):
    """A cgroup v2 holding the step and everything it starts.

    With `parent`, the cgroup is made there by bake, and the step's command
    moves itself into it before exec.  With `scope_unit`, systemd-run makes
    it, a transient user scope, and its path is known once the command runs.
    """

    mechanism = "cgroup"

    def __init__(self, parent=None, scope_unit=None, cgroup_root=CGROUP_ROOT):
        super().__init__()
        self.cgroup_root = Path(cgroup_root)
        self.scope_unit = scope_unit
        self.path = None
        if parent is not None:
            parent = Path(parent)
            cleanup_stale(parent, "bake.{pid}.")
            self.path = parent / f"bake.{os.getpid()}.{next(_steps)}"
            self.path.mkdir()
            procs_file = str(self.path / "cgroup.procs")

            def preexec():
                fd = os.open(procs_file, os.O_WRONLY)
                try:
                    os.write(fd, str(os.getpid()).encode())
                finally:
                    os.close(fd)

            self.preexec = preexec

    @property
    def where(self):
        return f"cgroup {self.path}" if self.path else f"scope {self.scope_unit}"

    def command(self, cmd):
        if self.scope_unit is None:
            return cmd
        # exec: the step's process is systemd-run's, which moves into the scope
        return (f"exec systemd-run --user --scope --quiet --collect --unit={self.scope_unit} -- "
                f"sh -c {shlex.quote(cmd)}")

    def started(self, proc):
        super().started(proc)
        if self.path is not None:
            return
        # systemd-run moves itself into the scope, then execs the command.
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and proc.poll() is None:
            path = own_cgroup(proc.pid)
            if path is not None and path.endswith(f"/{self.scope_unit}.scope"):
                self.path = self.cgroup_root / path.lstrip("/")
                logging.debug("Step processes are in cgroup %s", self.path)
                cleanup_stale(self.path.parent, "bake-{pid}-")
                return
            time.sleep(0.05)
        if proc.poll() is None:
            logging.warning("The scope %s did not appear; tracking the step's descendants only.",
                            self.scope_unit)

    def pids(self):
        if self.path is None:
            # The scope is not there yet (or never came): what the command started.
            if self.proc is None:
                return set()
            procs, todo, found = _processes(), [self.proc.pid], set()
            while todo:
                pid = todo.pop()
                if pid in procs and procs[pid][2] != "Z":
                    found.add(pid)
                todo.extend(p for p, st in procs.items() if st[0] == pid)
            return found
        return {pid for pid in cgroup_pids(self.path) if _alive(pid)}

    def kill(self):
        reached = len(self.pids())
        if self.path is not None:
            try:
                (self.path / "cgroup.kill").write_text("1", encoding="utf-8")
            except OSError:
                pass   # before Linux 5.14; the signals below do it
        self.send(signal.SIGKILL)
        return reached

    def close(self):
        if self.path is None or self.scope_unit is not None:
            return   # systemd removes the scope (--collect)
        remove_cgroup(self.path)


# ---------------------------------------------------------------------------
# cgroup helpers
# ---------------------------------------------------------------------------

def own_cgroup(pid="self"):
    """The cgroup v2 path of a process, as /proc gives it ('/a/b'); None
    without a unified hierarchy."""
    try:
        lines = Path(f"/proc/{pid}/cgroup").read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in lines:
        if line.startswith("0::"):
            return line[3:]
    return None


def cgroup_pids(path):
    """The processes in a cgroup and in the cgroups below it."""
    found = set()
    for directory, _, _ in os.walk(path):
        try:
            text = (Path(directory) / "cgroup.procs").read_text(encoding="utf-8")
        except OSError:
            continue
        found.update(int(p) for p in text.split())
    return found


def remove_cgroup(path, wait=2.0):
    """Remove a cgroup and those below it, once their processes are gone."""
    deadline = time.monotonic() + wait
    while any(_alive(pid) for pid in cgroup_pids(path)) and time.monotonic() < deadline:
        time.sleep(0.05)
    for directory, _, _ in sorted(os.walk(path), key=lambda d: -len(d[0])):
        try:
            os.rmdir(directory)
        except OSError as err:
            logging.debug("Cannot remove cgroup %s: %s", directory, err)


def cleanup_stale(parent, prefix):
    """End the processes left in the cgroups of bakes that are gone: those in
    `parent` named `prefix` (with `{pid}`, the bake's) and a number."""
    head, _, tail = prefix.partition("{pid}")
    try:
        entries = list(os.scandir(parent))
    except OSError:
        return
    for entry in entries:
        if not entry.is_dir() or not entry.name.startswith(head):
            continue
        owner, sep, _ = entry.name[len(head):].partition(tail)
        if not sep or not owner.isdigit() or int(owner) == os.getpid() or _owner_alive(int(owner)):
            continue
        path = Path(entry.path)
        left = sorted(pid for pid in cgroup_pids(path) if _alive(pid))
        if left:
            logging.info("Killing %d processes left by an earlier bake (pid %s) in %s:", len(left), owner, path)
            for pid in left:
                logging.info("   %7d  %s", pid, describe(pid))
            try:
                (path / "cgroup.kill").write_text("1", encoding="utf-8")
            except OSError:
                pass
            for pid in left:
                _kill(pid, signal.SIGKILL)
        if not entry.name.endswith(".scope"):
            remove_cgroup(path)


def _owner_alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    return True


def _cgroup_mount(root):
    """The mount options of the cgroup2 file system at `root`, None when
    there is none."""
    options = None
    try:
        lines = Path("/proc/self/mountinfo").read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in lines:
        fields = line.split()
        sep = fields.index("-")
        if fields[4] == str(root) and fields[sep + 1] == "cgroup2":
            options = fields[5].split(",")   # the last mount on top wins
    return options


def _own_cgroup_parent(root=CGROUP_ROOT):
    """bake's own cgroup when it can make cgroups below it; otherwise None
    and why not."""
    options = _cgroup_mount(root)
    if options is None:
        return None, f"no cgroup v2 file system at {root}"
    if "ro" in options:
        return None, f"{root} is mounted read-only"
    own = own_cgroup()
    if own is None:
        return None, "bake is in no cgroup v2"
    path = root / own.lstrip("/")
    if not (os.access(path, os.W_OK) and os.access(path / "cgroup.procs", os.W_OK)):
        return None, f"bake's cgroup {path} is not writable"
    return path, None


def _systemd_user():
    """Whether systemd-run can make user scopes; otherwise why not."""
    if shutil.which("systemd-run") is None:
        return False, "systemd-run not found"
    try:
        proc = subprocess.run(["systemctl", "--user", "show-environment"],
                              capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired) as err:
        return False, f"systemctl --user: {err}"
    if proc.returncode:
        first = (proc.stderr.strip().splitlines() or ["failed"])[0]
        return False, f"no systemd user manager ({first})"
    return True, None


# ---------------------------------------------------------------------------
# Choosing a tracker
# ---------------------------------------------------------------------------

def track():
    """A tracker for the next step, by `config.bake.process_tracking`.  The
    mechanism, and why a better one is not used, is logged once per run."""
    wanted = context.config.bake.process_tracking
    if wanted not in MECHANISMS:
        raise exceptions.BakeConfigError(
            f"config.bake.process_tracking is '{wanted}'; expected one of {', '.join(MECHANISMS)}.")

    reasons = []
    if wanted in ("auto", "cgroup"):
        parent, why = _own_cgroup_parent()
        if parent is not None:
            tracker = CgroupTracker(parent=parent)
            _announce(f"cgroup:{parent}", "Flow processes are tracked in cgroups under %s.", parent)
            return tracker
        reasons.append(why)
        ok, why = _systemd_user()
        if ok:
            tracker = CgroupTracker(scope_unit=f"bake-{os.getpid()}-{next(_steps)}")
            _announce("scope", "Flow processes are tracked in cgroups, as systemd user scopes.")
            return tracker
        reasons.append(why)
        if wanted == "cgroup":
            raise exceptions.BakeRuntimeError(
                "config.bake.process_tracking is 'cgroup', but bake cannot make cgroups here: "
                + "; ".join(reasons) + ".")

    if wanted in ("auto", "subreaper"):
        try:
            tracker = SubreaperTracker()
        except (OSError, AttributeError) as err:
            if wanted == "subreaper":
                raise exceptions.BakeRuntimeError(f"bake cannot be a child subreaper here: {err}.") from err
            reasons.append(f"no child subreaper: {err}")
        else:
            why = f", as cgroups are unavailable: {'; '.join(reasons)}" if reasons else ""
            _announce("subreaper", f"Flow processes are tracked as bake's children (subreaper){why}. "
                      "A bake killed with SIGKILL can still leave them running.")
            return tracker

    why = f" ({'; '.join(reasons)})" if reasons else ""
    _announce("group", "Flow processes are tracked by process group%s: "
              "those that leave it are not reached.", why)
    return GroupTracker()


def _announce(key, message, *args):
    if context.process_tracking != key:
        context.process_tracking = key
        logging.info(message, *args)
