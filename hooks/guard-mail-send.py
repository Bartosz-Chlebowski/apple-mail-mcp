#!/usr/bin/env python3
# PreToolUse hook for mail_send: a send goes through only after the user approved it in the chat.
#
# Claude Code passes the path of the conversation file. The hook allows mail_send only when
#   - the call comes from the main conversation, not from a subagent,
#   - the draft is the one the latest mail_draft call in this conversation made,
#   - the user's last message came after that draft, holds nothing but approval words
#     ("send", "yes", "tak", "wyślij", ...) and no question mark,
#   - no other mail_send used that message. One approval covers one send.
# The user's messages are the ones Claude Code marks as typed by a human. Notes Claude Code adds to a
# message (<system-reminder>, <artifact-view-context>) are left out. A message typed while the model was
# working never approves: Claude Code files it after the result of the tool that was running, so it can
# look newer than a draft the user has not seen. It only cancels an earlier approval. Background tasks,
# system notes, summaries, subagents and prompts from scripts never count.
# Claude Code writes a call to the file only after its hooks ran, so a used approval is also marked in
# ~/Library/Caches/apple-mail-mcp/approvals, which stops two calls in one message from sharing it.
# Anything else, including a file it cannot read or an error in the hook itself, blocks the call with
# exit 2. It blocks instead of asking, so it also works when tool approvals are skipped. Register it with
# "onFailure": "block", so a hook that cannot start blocks too.
# It stops a model that sends too early, not one that works against you: a model with Bash can edit the
# conversation file or this hook. Only permissions.deny for mail_send stops sends for sure.
# Test: hooks/test-guard-mail-send.py
import hashlib
import json
import os
import re
import sys
import unicodedata

# A message approves only when every word is in APPROVE or FILLER and at least one is in APPROVE.
# Add your language here.
APPROVE = {
    "yes", "yep", "yeah", "send", "approve", "approved", "go", "sure",
    "tak", "wyślij", "wyslij", "wysłać", "wyslac", "wysyłaj", "wysylaj", "wysyłamy", "wysylamy", "leci", "dawaj",
    "śmiało", "smialo", "jasne", "zatwierdzam", "akceptuję", "akceptuje", "zgoda",
}
FILLER = {
    "ok", "okay", "it", "this", "now", "please", "the", "mail", "email", "ahead",
    "okej", "to", "ją", "je", "tego", "teraz", "już", "juz", "proszę", "prosze", "pls", "maila", "możesz",
    "mozesz", "dobrze",
}
NOTES = re.compile(r"<(system-reminder|artifact-view-context)\b[^>]*>.*?</\1\s*>", re.S)
DRAFT_ID = re.compile(r"^draft_id=(\d+) \|", re.M)  # the first one is the draft; a subject comes later
ASK = ("Show the user the draft (recipients, subject, text, signature, attachments) and wait for a plain "
       'answer like "send" or "yes". Do not look for a way around this check.')
LATEST = ("Only the draft from the latest mail_draft call can be sent, one at a time: draft, approval, send. "
          "For an older draft, make it again with mail_draft and close the old one with mail_discard, or the user "
          "presses Send in Mail. Do not look for a way around this check.")
USED = "the user's last approval was already used. One approval covers one send."


def block(reason, then=ASK):
    print(f"mail_send blocked: {reason} {then}", file=sys.stderr)
    return 2


def text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return ""


def approves(text):
    text = unicodedata.normalize("NFC", NOTES.sub(" ", text)).lower()
    words = re.findall(r"[^\W\d_]+", text)
    return ("?" not in text and bool(words) and all(w in APPROVE or w in FILLER for w in words)
            and any(w in APPROVE for w in words))


def human(origin):
    return isinstance(origin, dict) and origin.get("kind") == "human"


def main():
    data = json.load(sys.stdin)
    if not isinstance(data, dict) or not isinstance(data.get("tool_name"), str):
        return block("the hook got no valid input.")
    if not data["tool_name"].endswith("__mail_send"):
        return 0
    if data.get("agent_id"):
        return block("a subagent called mail_send. Only the main conversation sends, after the user's approval.")
    args = data.get("tool_input")
    did = str(args.get("draft_id", "")).strip() if isinstance(args, dict) else ""
    path = data["transcript_path"]
    names, finished, sends = {}, set(), []
    latest = mark = None
    approved = drafted = False
    with open(path, encoding="utf-8", errors="replace") as f:
        for n, raw in enumerate(f):
            try:
                e = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(e, dict) or e.get("isSidechain"):
                continue
            message = e.get("message")
            content = message.get("content") if isinstance(message, dict) else None
            blocks = [b for b in content if isinstance(b, dict)] if isinstance(content, list) else []
            kind = e.get("type")
            if kind == "assistant":
                for b in blocks:
                    name = str(b.get("name", "")) if b.get("type") == "tool_use" else ""
                    if name.endswith("__mail_draft"):
                        names[b.get("id")] = "draft"
                        drafted = True
                    elif name.endswith("__mail_send"):
                        names[b.get("id")] = "send"
                        sends.append(b.get("id"))
            elif kind == "user":
                results = [b for b in blocks if b.get("type") == "tool_result"]
                for b in results:
                    tool = names.get(b.get("tool_use_id"))
                    if tool == "draft":  # a draft that failed leaves no draft to approve
                        m = DRAFT_ID.search(text_of(b.get("content")))
                        latest = m[1] if m else None
                    elif tool == "send":
                        finished.add(b.get("tool_use_id"))
                if results:
                    continue
                if human(e.get("origin")) and not e.get("isMeta") and not e.get("isCompactSummary"):
                    approved, drafted, sends, mark = approves(text_of(content)), False, [], e.get("uuid") or n
                elif text_of(content).startswith("[Request interrupted by user"):
                    approved = False
            elif kind == "attachment":
                a = e.get("attachment")  # a message typed while the model was working
                if isinstance(a, dict) and a.get("type") == "queued_command" and human(a.get("origin")):
                    approved = False
    current = data.get("tool_use_id")
    used = [s for s in sends if s != current] if current else [s for s in sends if s in finished]
    if latest is None or did != latest:
        return block(f"draft {did or '(none)'} is not the one the latest mail_draft call in this conversation "
                     "made.", LATEST)
    if drafted:
        return block("a draft was made after the user's last message.")
    if used:
        return block(USED)
    if not approved:
        return block("the user's last message is not a plain approval of this draft.")
    marks = os.path.expanduser("~/Library/Caches/apple-mail-mcp/approvals")
    os.makedirs(marks, exist_ok=True)
    key = hashlib.sha256(f"{path}\n{mark}".encode()).hexdigest()[:40]
    try:
        os.close(os.open(os.path.join(marks, key), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600))
    except FileExistsError:
        return block(USED)
    return 0


if __name__ == "__main__":
    try:
        code = main()
    except Exception as err:  # any failure blocks the send, never lets it through
        code = block(f"the hook could not check the conversation ({type(err).__name__}).")
    sys.exit(code)
