# Terminal recording for the README and docs. From the repo root:
#   vhs docs/assets/demo.tape
# It runs the clone's tavla against a throwaway `tavla demo` repo.

Output docs/assets/demo.gif

Set Shell "bash"
Set FontSize 14
Set Width 1500
Set Height 470
Set Padding 24
Set Theme "Catppuccin Mocha"
Set TypingSpeed 45ms

Hide
Type "export TAVLA_CONTENT_DIR=$(mktemp -d)/demo PS1='$ '" Enter
Type "alias tv='uv run --quiet tv'" Enter
Type "tv demo $TAVLA_CONTENT_DIR > /dev/null && clear" Enter
Sleep 3s
Show

Type "tv next" Sleep 400ms Enter
Sleep 4s

Type "tv task done run-baseline" Sleep 400ms Enter
Sleep 3s
Ctrl+L

Type "tv flow thesis --open" Sleep 400ms Enter
Sleep 8s
