#!/bin/bash
# Test for guard-mail-applescript.py: AppleScript that reads Mail through collections -> 2; a draft, accounts, the
# selection, one message by id, other apps and plain file work -> 0. The blocked cases are scripts that froze Mail
# in real sessions, plus bypasses found in review. The session folder (cwd) is the folder with the test files.
# HOOK=/usr/bin/true ./test-guard-mail.sh must come out RED (proof that the test can fail).
cd "$(dirname "$0")" || exit 1
HOOK="${HOOK:-$PWD/guard-mail-applescript.py}"
TMPD=$(mktemp -d); trap 'rm -rf "$TMPD"' EXIT
printf 'tell application "Mail"\nset mb to mailbox "INBOX" of account id "X"\nset ss to sender of messages 1 thru 15 of mb\nend tell\n' > "$TMPD/inbox15.applescript"
printf 'tell application "Mail"\nset m to make new outgoing message with properties {subject:"x", visible:false}\nend tell\n' > "$TMPD/draft.applescript"
fail=0
run(){ # $1 expected exit code, $2 tool, $3 command or script
  code=$(python3 -c 'import json,sys; t=sys.argv[1]; k="code_snippet" if t.startswith("mcp__applescript") else ("script" if t.startswith("mcp__other") else "command"); print(json.dumps({"tool_name":t,"tool_input":{k:sys.argv[2]},"cwd":sys.argv[3]}))' "$2" "$3" "$TMPD" | "$HOOK" 2>/dev/null; echo $?)
  [ "$code" = "$1" ] && echo "ok   [$1] $(echo "${3:0:100}" | tr '\n' ' ')" || { echo "FAIL expected $1, got $code: $3"; fail=1; }
}
A=mcp__applescript-mcp__applescript_execute
T=mcp__terminal__run_in_terminal
# reading through collections -> blocked
run 2 Bash "osascript -e 'tell application \"Mail\"
repeat with a in accounts
repeat with mb in mailboxes of a
set u to unread count of mb
end repeat
end repeat
end tell'"
# a filter over accounts is cheap -> allowed
run 0 Bash "osascript <<'AS'
tell application \"Mail\"
  set acc to first account whose id is \"ACCOUNT-ID\"
end tell
AS"
run 2 Bash "cat > \"\$TMPDIR/x.applescript\" <<'EOF'
tell application \"Mail\"
set ids to id of messages 1 thru 15 of mailbox \"INBOX\" of account id \"X\"
end tell
EOF"
run 2 Bash "S=$TMPD/inbox15.applescript; osascript \"\$S\""
run 2 Bash "osascript $TMPD/inbox15.applescript 2>&1 | head"
run 2 Bash "cd $TMPD && osascript inbox15.applescript"
run 2 Bash "osascript inbox15.applescript"
run 2 Bash "osascript < inbox15.applescript"
run 2 Bash "osascript -e \"\$(cat $TMPD/inbox15.applescript)\""
run 2 Bash "osascript \"\$(pwd)/inbox15.applescript\""
run 2 Bash "osascript -e \"tell application \\\"Mail\\\" to get subject of every message of inbox\""
run 2 Bash "osascript -l JavaScript -e \"Application(\\\"Mail\\\").inbox.messages.subject()\""
run 2 Bash "osascript -l JavaScript -e 'const m = Application(\"Mail\"); m.inbox.messages().length'"
run 2 $A "delay 8
tell application \"Mail\"
set acc to account id \"X\"
repeat with mb in (mailboxes of acc)
set ms to (messages of mb whose subject is \"x\")
end repeat
end tell"
run 2 Bash "osascript -e 'tell application \"Mail\"
set mb to mailbox \"INBOX\" of account \"Google\"
repeat with i from 1 to 300
set m to message i of mb
end repeat
end tell'"
run 2 $A "tell application \"Mail\"
repeat with i from 1 to 50
set s to subject of message (i) of inbox
end repeat
end tell"
run 2 Bash "osascript -e 'tell application \"Mail\" to get subject of every message of mailbox \"INBOX\" of account \"Google\"'"
run 2 $A "tell application id \"com.apple.mail\" to count (messages of inbox)"
run 2 $A "tell application \"Mail\" to get subject of first message of inbox where subject contains \"x\""
run 2 $A "tell application \"Mail\" to get sender of message 1 thru 20 of inbox"
run 2 $T "osascript -e 'tell application \"Mail\" to count messages of inbox'"
run 2 Bash "python3 - <<'PY'
import subprocess
subprocess.run(['osascript', '-e', 'tell application \"Mail\" to get subject of messages of inbox'])
PY"
# Drafts next to another mailbox, a mailbox from a variable, "account whose" next to whose on INBOX, Sent -> blocked
run 2 $A "tell application \"Mail\"
set d to (messages of mailbox \"Drafts\" of account id \"X\" whose subject is \"y\")
set i to (messages of inbox whose subject is \"y\")
end tell"
run 2 $A "tell application \"Mail\" to get (messages of mailbox mbn of account id \"X\" whose subject contains \"y\")"
run 2 $A "tell application \"Mail\" to get source of (first message of mailbox \"INBOX\" of (first account whose id is \"X\") whose id is 12345)"
run 2 $A "tell application \"Mail\" to get subject of messages of sent mailbox"
run 2 $A "tell application \"Mail\" to get id of (messages of mailbox \"Gesendet\" of account id \"X\" whose subject is \"y\")"
# a draft, accounts, the selection, one message by id, other apps, file work -> allowed
run 0 Bash "osascript -e 'tell application \"Mail\"
set m to make new outgoing message with properties {subject:\"Subject\", content:\"Body\", visible:false}
make new to recipient at end of to recipients of m with properties {address:\"a@example.com\"}
save m
end tell'"
run 0 Bash "osascript -e 'tell application \"Mail\"
set m to make new outgoing message with properties {subject:\"CV\", content:\"Hi Anna, the person whose CV I sent is Tom. Thanks for your messages, see where we are.\", visible:false}
end tell'"
run 0 $A "set txt to \"Hello,\" & return & \"Thanks for the messages. Could you confirm whose wording we may use?\"
tell application \"Mail\"
set m to make new outgoing message with properties {subject:\"Approved wording\", content:txt, visible:false}
end tell"
run 0 Bash "osascript $TMPD/draft.applescript"
run 0 Bash "osascript -e 'tell application \"Mail\"
repeat with om in outgoing messages
set x to subject of om
end repeat
end tell'"
run 0 Bash "osascript -e 'tell application \"Mail\"
set o to \"\"
repeat with a in accounts
set o to o & (id of a) & linefeed
end repeat
end tell'"
run 0 Bash "osascript -e 'tell application \"Mail\"
repeat with m in (selection)
set s to subject of m
end repeat
end tell'"
run 0 $A "tell application \"Mail\" to get subject of «class mssg» id 12345 of mailbox \"INBOX\" of account id \"X\""
run 0 Bash "osascript -e 'tell application \"Finder\" to get name of every window'"
run 0 Bash "osascript -e 'tell application \"Messages\" to get name of every chat'"
run 0 $A "display notification \"Done\" with title \"Claude\""
run 0 Bash "grep -n osascript $TMPD/inbox15.applescript"
run 0 Bash "cat inbox15.applescript && sed -n 1,3p inbox15.applescript"
run 0 Bash "python3 harness.py '[[\"mail_recent\",{}]]'"
run 0 $T "open -g -a Mail"
# replacing drafts: only Drafts or Outbox, a filter over accounts, the signature inside a loop
run 0 Bash "osascript <<'AS'
tell application \"Mail\"
set mb to mailbox \"Drafts\" of account id \"X\"
set old to (messages of mb whose subject is \"Offer\")
repeat with d in old
delete d
end repeat
set m to make new outgoing message with properties {subject:\"Offer\", content:\"Check your inbox and the messages from us.\", visible:false}
set message signature of m to missing value
save m
end tell
AS"
run 0 $A "tell application \"Mail\"
set acc to first account whose id is \"X\"
set m to make new outgoing message with properties {sender:\"a@example.com\", subject:\"x\", visible:false}
end tell"
run 0 $A "tell application \"Mail\" to count (messages of outbox whose subject contains \"AI\")"
run 0 $A "tell application \"Mail\" to close (every outgoing message whose subject is \"x\") saving no"
run 0 $A "tell application \"Mail\"
repeat with adr in {\"a@example.com\", \"b@example.com\"}
set m to make new outgoing message with properties {subject:\"x\", visible:false}
set message signature of m to missing value
end repeat
end tell"
# localized Drafts names
run 0 $A "tell application \"Mail\" to get id of (messages of mailbox \"[Gmail]/Wersje robocze\" of account id \"X\" whose subject is \"y\")"
run 0 $A "tell application \"Mail\" to get id of (messages of mailbox \"Entwürfe\" of account id \"X\" whose subject is \"y\")"
# one script split over several -e -> blocked; a draft split the same way -> allowed
run 2 Bash "osascript -e 'tell application \"Mail\"' -e 'get subject of every message of inbox' -e 'end tell'"
run 0 Bash "osascript -e 'tell application \"Mail\"' -e 'set m to make new outgoing message with properties {subject:\"x\"}' -e 'end tell'"
# a script piped into osascript -> blocked; accounts piped in, or a commit message about osascript -> allowed
run 2 Bash "echo 'tell application \"Mail\" to get subject of every message of inbox' | osascript"
run 2 Bash "printf '%s' 'tell application \"Mail\" to count messages of inbox' | osascript 2>&1"
run 0 Bash "echo 'tell application \"Mail\" to get name of every account' | osascript"
run 0 Bash "git commit -m 'guard: osascript with tell application \"Mail\" and every message is blocked'"
run 0 Bash "grep -n 'every message whose' server.py"
# \$VAR from the same command -> expanded
run 2 Bash "S='tell application \"Mail\" to get subject of every message of inbox'; osascript -e \"\$S\""
run 0 Bash "S='tell application \"Mail\" to get name of every account'; osascript -e \"\$S\""
# timeout and sh -c in front of osascript
run 2 Bash "timeout 20 osascript inbox15.applescript"
run 2 Bash "timeout -s KILL 20 osascript -e 'tell application \"Mail\" to get subject of every message of inbox'"
run 0 Bash "timeout 20 osascript -e 'tell application \"Mail\" to get name of every account'"
run 2 Bash "bash -c \"osascript inbox15.applescript\""
run 2 Bash "zsh -lc 'osascript -e \"tell application \\\"Mail\\\" to count messages of inbox\"'"
run 0 Bash "bash -c \"osascript -e 'tell application \\\"Finder\\\" to get name of every window'\""
# Mail by its path
run 2 $A "tell application \"/System/Applications/Mail.app\" to get subject of every message of inbox"
run 0 $A "tell application \"/System/Applications/Mail.app\" to get name of every account"
# comments do not count, but they do not hide code either
run 0 $A "-- where to send it: ask the user, never search all messages
tell application \"Mail\"
(* every message whose... is forbidden *)
set m to make new outgoing message with properties {subject:\"x\"} # messages go out later
end tell"
run 0 Bash "osascript -l JavaScript -e 'const mail = Application(\"Mail\"); // never read every message here
mail.OutgoingMessage({subject: \"x\"})'"
run 2 $A "tell application \"Mail\" to get subject of every message of inbox -- just a quick look"
# a script file piped in, and another AppleScript tool that passes "script"
run 2 Bash "cat inbox15.applescript | osascript"
run 0 Bash "cat draft.applescript | osascript"
O=mcp__other__run_applescript
run 2 $O "tell application \"Mail\" to get subject of every message of inbox"
run 0 $O "tell application \"Mail\" to get name of every account"
# Mail.app by name, raw class codes, a here-string, export and nice in front -> blocked; the selection -> allowed
run 2 $A "tell application \"Mail.app\" to get subject of every message of inbox"
run 2 Bash "osascript -l JavaScript -e 'Application(\"Mail.app\").inbox.messages.subject()'"
run 0 $A "tell application \"Mail.app\" to get name of every account"
run 2 $A "tell application \"Mail\" to get subject of every «class mssg» of inbox"
run 2 $A "tell application \"Mail\" to get sender of «class mssg» 1 thru 20 of inbox"
run 2 Bash "osascript <<< 'tell application \"Mail\" to count messages of inbox'"
run 0 Bash "osascript <<< 'tell application \"Mail\" to get name of every account'"
run 2 Bash "export S='tell application \"Mail\" to get subject of every message of inbox'; osascript -e \"\$S\""
run 2 Bash "nice osascript inbox15.applescript"
run 0 $A "tell application \"Mail\" to get subject of selected messages of message viewer 1"
# a blank line or ";" and a line end between commands
run 2 Bash "set -e

osascript -e 'tell application \"Mail\" to count messages of inbox'"
run 2 Bash "cd /tmp;
osascript -e 'tell application \"Mail\" to count messages of inbox'"
# sending through Mail would skip the approval before mail_send -> blocked;
# send in a string or a comment, sender, another app -> allowed
run 2 $A "tell application \"Mail\" to send (make new outgoing message with properties {subject:\"x\", visible:true})"
run 2 Bash "osascript -e 'tell application \"Mail\"' -e 'send front outgoing message' -e 'end tell'"
run 2 Bash "osascript -l JavaScript -e 'Application(\"Mail\").outgoingMessages()[0].send()'"
run 2 $A "tell application \"Mail\" to «event emsgsend» (front outgoing message)"
run 0 $A "tell application \"Mail\" to make new outgoing message with properties {subject:\"send this\", visible:true}"
run 0 $A "tell application \"Mail\" to activate -- do not send"
run 0 $A "tell application \"Mail\" to get sender of item 1 of (get selection)"
run 0 $A "tell application \"Messages\" to send \"hi\" to buddy \"x\""
[ $fail = 0 ] && echo "RESULT: green" || { echo "RESULT: RED"; exit 1; }
