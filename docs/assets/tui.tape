# Recording of `tv ui` for the README and docs. From the repo root:
#   vhs docs/assets/tui.tape
# It runs the clone's tavla against a throwaway `tavla demo` repo.

Output docs/assets/tui.gif

Set Shell "bash"
Set FontSize 14
Set Width 1500
Set Height 760
Set Padding 16
Set Theme "Catppuccin Mocha"
Set TypingSpeed 60ms

Hide
Type "export TAVLA_CONTENT_DIR=$(mktemp -d)/demo XDG_CACHE_HOME=$(mktemp -d) PS1='$ '" Enter
Type "alias tv='uv run --quiet tv'" Enter
Type "tv demo $TAVLA_CONTENT_DIR > /dev/null && clear" Enter
Sleep 3s
Show

Type "tv" Sleep 400ms Enter
Sleep 3s

# Pick the thesis, then a goal's tasks and a task's preview: tick a subtask.
Type "P" Sleep 800ms
Type "thesis" Sleep 600ms Enter
Sleep 1.5s
Type "j" Sleep 900ms
Type "l" Sleep 1.2s
Type "l" Sleep 1.5s
Space Sleep 2s
Type "h" Sleep 1s

# The flow board of the goal.
Type "h" Sleep 600ms
Type "f" Sleep 4s
Type "q" Sleep 1s

# What to do next, then the inbox and the agenda.
Type "2" Sleep 2.5s
Type "3" Sleep 2.5s
Type "4" Sleep 3s

# Capture an idea from anywhere.
Type "c" Sleep 800ms
Type "try a warm-up schedule #speed" Sleep 600ms Enter
Sleep 2s
Type "3" Sleep 3s

Type "q"
Sleep 1s
