# Sourced by reset.sh and create-board.sh; needs REPO set.
#
# A board's driver pid is in runs/driver.lock (acquire_lock). A killed driver leaves the
# lock behind and the pid may since belong to anything, so only a process running THIS
# repo's mission/run.py counts, however it was started (`mission/run.py`,
# `cd mission; python3 run.py`, an absolute path) — an argument ending in run.py,
# resolved against the process's own cwd. A zombie counts as gone.
alive() { s=$(ps -o stat= -p "$1" 2>/dev/null) && [ -n "$s" ] && [ "${s#Z}" = "$s" ]; }
runs_this_driver() {
  local arg want
  want=$(realpath -m "$REPO/mission/run.py")
  [ -r "/proc/$1/cmdline" ] || return 1
  while IFS= read -r -d '' arg; do
    case "$arg" in
      *run.py)
        [ "${arg#/}" = "$arg" ] && arg="$(readlink "/proc/$1/cwd" 2>/dev/null)/$arg"
        [ "$(realpath -m "$arg")" = "$want" ] && return 0 ;;
    esac
  done < "/proc/$1/cmdline"
  return 1
}
# The pid named by <board-dir>/runs/driver.lock, or nothing.
lock_pid() {
  local pid
  pid=$(cat "$1/runs/driver.lock" 2>/dev/null || true)
  case "$pid" in ''|*[!0-9]*) pid= ;; esac
  echo "$pid"
}
# Prints the pid of this board's live driver; fails when none runs.
live_driver_pid() {
  local pid
  pid=$(lock_pid "$1")
  [ -n "$pid" ] && alive "$pid" && runs_this_driver "$pid" && echo "$pid"
}
