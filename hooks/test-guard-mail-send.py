#!/usr/bin/env python3
# Test for guard-mail-send.py: should end with RESULT: green.
# HOOK=/usr/bin/true hooks/test-guard-mail-send.py should end with RESULT: RED, which proves the test can fail.
# Run it with another python3 to test the hook on that version.
import json
import os
import subprocess
import sys
import tempfile
import unicodedata

HOOK = os.environ.get("HOOK") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "guard-mail-send.py")
SEND, DRAFT = "mcp__apple-mail__mail_send", "mcp__apple-mail__mail_draft"


def msg(role, content, **flags):
    return {"type": role, "isSidechain": False, "message": {"role": role, "content": content}, **flags}


def human(text, **flags):
    return msg("user", text, origin={"kind": "human"}, **flags)


def call(name, tid, args, side=False):
    return msg("assistant", [{"type": "tool_use", "id": tid, "name": name, "input": args}], isSidechain=side)


def result(tid, text, side=False):
    return msg("user", [{"type": "tool_result", "tool_use_id": tid, "content": [{"type": "text", "text": text}]}],
               isSidechain=side)


def draft(tid, did, side=False, head="Draft created in a Mail window:", subject="Hi"):
    return [call(DRAFT, tid, {"to": ["a@example.com"], "subject": subject}, side),
            result(tid, f"{head}\ndraft_id={did} | window open | from: (default) | to: a@example.com | "
                        f"subject: {subject} | signature: none", side)]


def send(tid, did=5):
    return call(SEND, tid, {"draft_id": did})


def queued(text, kind="human"):
    """A message typed while the model was working, stored only as an attachment."""
    return {"type": "attachment", "attachment": {"type": "queued_command", "prompt": text, "origin": {"kind": kind},
                                                 "commandMode": "prompt" if kind == "human" else kind}}


NOTE = msg("user", "<task-notification>done</task-notification>", origin={"kind": "task-notification"})
ASKED = [human("napisz maila"), *draft("d1", 5)]
TWO = [human("dwa maile"), *draft("d1", 5), *draft("d2", 6)]
# Notes Claude Code adds to a message. Their words and question marks must not count.
REMINDER = "<system-reminder>\nIs this a note? tak\n</" + "system-reminder>"
VIEW = '<artifact-view-context artifact="https://claude.ai/artifact/x">\nOpen page? send\n</artifact-view-context>'

# name, expected exit code, transcript entries, draft_id sent, tool_use_id of the call being checked
CASES = [
    ("plain yes after the draft", 0, [*ASKED, human("tak"), send("s1")], 5, "s1"),
    ("yes with punctuation", 0, [*ASKED, human("Tak, wyślij!"), send("s1")], 5, "s1"),
    ("approval with filler words", 0, [*ASKED, human("ok wyslij to"), send("s1")], 5, "s1"),
    ("English approval", 0, [*ASKED, human("Send it."), send("s1")], 5, "s1"),
    ("go ahead", 0, [*ASKED, human("Go ahead"), send("s1")], 5, "s1"),
    ("możesz wysłać", 0, [*ASKED, human("Możesz wysłać"), send("s1")], 5, "s1"),
    ("dobrze, zgoda", 0, [*ASKED, human("Dobrze, zgoda."), send("s1")], 5, "s1"),
    ("approval as text blocks", 0, [*ASKED, human([{"type": "text", "text": "leci"}]), send("s1")], 5, "s1"),
    ("decomposed Unicode", 0, [*ASKED, human(unicodedata.normalize("NFD", "wyślij")), send("s1")], 5, "s1"),
    ("approval after a note block", 0, [*ASKED, human([{"type": "text", "text": REMINDER},
                                                       {"type": "text", "text": "tak"}]), send("s1")], 5, "s1"),
    ("approval after a page note", 0, [*ASKED, human(VIEW + "\ntak"), send("s1")], 5, "s1"),
    ("queued task notification after approval", 0, [*ASKED, human("tak"), queued("<task-notification>x",
                                                                                   "task-notification"),
                                                     send("s1")], 5, "s1"),
    ("odd lines are skipped", 0, [*ASKED, [], {"type": "user", "message": "x"}, {"type": "attachment",
                                                                                "attachment": "x"},
                                  human("tak"), send("s1")], 5, "s1"),
    ("task notification after approval", 0, [*ASKED, human("tak"), NOTE, send("s1")], 5, "s1"),
    ("system note after approval", 0, [*ASKED, human("tak"), msg("user", REMINDER, isMeta=True), send("s1")],
     5, "s1"),
    ("reply draft", 0, [human("odpowiedz"), *draft("d1", 7, head="Reply draft created:"), human("tak"),
                        send("s1", 7)], 7, "s1"),
    ("broken line in the file", 0, [*ASKED, "{not json", human("tak"), send("s1")], 5, "s1"),
    ("no tool_use_id, call not written yet", 0, [*ASKED, human("tak")], 5, None),
    ("no tool_use_id, call written", 0, [*ASKED, human("tak"), send("s1")], 5, None),
    ("latest of two drafts", 0, [*TWO, human("tak"), send("s1", 6)], 6, "s1"),
    ("subject with draft_id in it", 0, [human("napisz"), *draft("d1", 5, subject="draft_id=9 | x"), human("tak"),
                                        send("s1")], 5, "s1"),
    ("no message after the draft", 2, [human("napisz i wyślij"), *draft("d1", 5), send("s1")], 5, "s1"),
    ("ok alone", 2, [*ASKED, human("ok"), send("s1")], 5, "s1"),
    ("emoji alone", 2, [*ASKED, human("👍"), send("s1")], 5, "s1"),
    ("question", 2, [*ASKED, human("Wysłać?"), send("s1")], 5, "s1"),
    ("note alone", 2, [*ASKED, human([{"type": "text", "text": REMINDER}]), send("s1")], 5, "s1"),
    ("correction", 2, [*ASKED, human("zmień temat na Oferta"), send("s1")], 5, "s1"),
    ("no", 2, [*ASKED, human("nie wysyłaj"), send("s1")], 5, "s1"),
    ("No, send it", 2, [*ASKED, human("No, send it"), send("s1")], 5, "s1"),
    ("yes with a change", 2, [*ASKED, human("tak, ale zmień temat"), send("s1")], 5, "s1"),
    ("approval with a recipient", 2, [*ASKED, human("wyślij do Marka"), send("s1")], 5, "s1"),
    ("interrupt after approval", 2, [*ASKED, human("tak"), msg("user", "[Request interrupted by user]"),
                                     send("s1")], 5, "s1"),
    ("approval typed while the model worked", 2, [*ASKED, queued("tak"), send("s1")], 5, "s1"),
    ("yes typed while the model worked, after approval", 2, [*ASKED, human("tak"), queued("tak"), send("s1")],
     5, "s1"),
    ("change typed while the model worked", 2, [*ASKED, human("tak"), queued("czekaj, zmień temat"), send("s1")],
     5, "s1"),
    ("message without origin", 2, [*ASKED, msg("user", "tak"), send("s1")], 5, "s1"),
    ("artifact comment saying yes", 2, [*ASKED, human("[Artifact comment sent to Claude] tak"), send("s1")],
     5, "s1"),
    ("pasted yes", 2, [*ASKED, human('<pasted_content id="3ada">\ntak\n</pasted_content>'), send("s1")], 5, "s1"),
    ("script prompt saying yes", 2, [*ASKED, msg("user", "tak", promptSource="sdk"), send("s1")], 5, "s1"),
    ("whole file from a subagent", 2, [dict(e, isSidechain=True) for e in [*ASKED, human("tak"), send("s1")]],
     5, "s1"),
    ("draft made after approval", 2, [*ASKED, human("tak"), *draft("d2", 6), send("s1")], 5, "s1"),
    ("older of two drafts", 2, [*TWO, human("tak"), send("s1", 5)], 5, "s1"),
    ("failed draft after a good one", 2, [*ASKED, call(DRAFT, "d2", {}), result("d2", "Mail is busy."),
                                          human("tak"), send("s1")], 5, "s1"),
    ("id taken from the subject", 2, [human("napisz"), *draft("d1", 5, subject="draft_id=9 | x"), human("tak"),
                                      send("s1", 9)], 9, "s1"),
    ("id on a later line of the subject", 2, [human("napisz"), *draft("d1", 5, subject="Hi\ndraft_id=9 | x"),
                                              human("tak"), send("s1", 9)], 9, "s1"),
    ("second send after one approval", 2, [*TWO, human("tak"), send("s1", 6), result("s1", "Sent: Hi"),
                                           send("s2", 6)], 6, "s2"),
    ("second send, no tool_use_id", 2, [*TWO, human("tak"), send("s1", 6), result("s1", "Sent: Hi")], 6, None),
    ("two sends in one message", 2, [*TWO, human("tak"), send("s1", 6), send("s2", 6)], 6, "s2"),
    ("retry after a failed send", 2, [*ASKED, human("tak"), send("s1"), result("s1", "Mail is busy."),
                                      send("s2")], 5, "s2"),
    ("draft not made here", 2, [*ASKED, human("tak"), send("s1", 999)], 999, "s1"),
    ("draft made in a subagent", 2, [human("napisz"), *draft("d1", 5, side=True), human("tak"), send("s1")],
     5, "s1"),
    ("approval only in a subagent", 2, [*ASKED, human("tak", isSidechain=True), send("s1")], 5, "s1"),
    ("task notification saying yes", 2, [*ASKED, msg("user", "tak", origin={"kind": "task-notification"}),
                                         send("s1")], 5, "s1"),
    ("summary after compaction saying yes", 2, [*ASKED, msg("user", "tak", isCompactSummary=True), send("s1")],
     5, "s1"),
    ("draft listed by mail_drafts only", 2, [human("wyślij szkic 5"), call("mcp__apple-mail__mail_drafts", "l1", {}),
                                             result("l1", "draft_id=5 | window open | to: a@example.com"),
                                             human("tak"), send("s1")], 5, "s1"),
    ("draft refused by Mail", 2, [human("napisz"), call(DRAFT, "d1", {}), result("d1", "Mail has no signature."),
                                  human("tak"), send("s1")], 5, "s1"),
    ("no draft_id", 2, [*ASKED, human("tak"), send("s1")], None, "s1"),
]


def run(stdin, home):
    """Runs the hook with HOME in a temp folder, so approval markers stay out of the real cache."""
    cmd = [sys.executable, HOOK] if HOOK.endswith(".py") else [HOOK]
    return subprocess.run(cmd, input=stdin, capture_output=True, text=True,
                          env=dict(os.environ, HOME=home)).returncode


def hook_input(path, did, tid, tool=SEND, **extra):
    data = {"tool_name": tool, "tool_input": {} if did is None else {"draft_id": did}, "transcript_path": path,
            **extra}
    if tid:
        data["tool_use_id"] = tid
    return json.dumps(data)


def write(path, entries):
    with open(path, "w", encoding="utf-8") as f:
        f.writelines((e if isinstance(e, str) else json.dumps(e, ensure_ascii=False)) + "\n" for e in entries)


bad = 0


def check(name, want, got):
    global bad
    bad += got != want
    print(f"{'ok  ' if got == want else 'FAIL'} [{want}] {name}" + ("" if got == want else f" (got {got})"))


with tempfile.TemporaryDirectory() as tmp:
    home = os.path.join(tmp, "home")
    os.mkdir(home)
    for i, (name, want, entries, did, tid) in enumerate(CASES):
        path = os.path.join(tmp, f"t{i}.jsonl")
        write(path, entries)
        check(name, want, run(hook_input(path, did, tid), home))
    # Claude Code writes a call to the file only after its hooks ran, so two calls in one message
    # see the same file. Only the first may use the approval.
    path = os.path.join(tmp, "parallel.jsonl")
    write(path, [*ASKED, human("tak")])
    check("first of two calls in one message", 0, run(hook_input(path, 5, "s1"), home))
    check("second of two calls in one message", 2, run(hook_input(path, 5, "s2"), home))
    write(path, [*ASKED, human("tak"), send("s1"), result("s1", "Sent: Hi"), *draft("d2", 6), human("tak")])
    check("new draft and new approval after a send", 0, run(hook_input(path, 6, "s3"), home))
    store = os.path.join(tmp, "store.jsonl")
    write(store, [*ASKED, human("tak")])
    for name, want, stdin, where in [
        ("other tool is not checked", 0, hook_input(store, 5, "s1", tool="Bash"), home),
        ("call from a subagent", 2, hook_input(store, 5, "s1", agent_id="a1", agent_type="general-purpose"), home),
        ("no tool_name", 2, json.dumps({"tool_input": {"draft_id": 5}, "transcript_path": store}), home),
        ("missing transcript", 2, hook_input(os.path.join(tmp, "none.jsonl"), 5, "s1"), home),
        ("no transcript path", 2, json.dumps({"tool_name": SEND, "tool_input": {"draft_id": 5}}), home),
        ("no input", 2, "", home),
        ("input is a list", 2, "[]", home),
        ("tool_input is text", 2, json.dumps({"tool_name": SEND, "tool_input": "5", "transcript_path": store}), home),
        ("approval store not writable", 2, hook_input(store, 5, "s1"), "/dev/null"),
        ("same call from the main conversation", 0, hook_input(store, 5, "s1"), home),
    ]:
        check(name, want, run(stdin, where))

print("RESULT: green" if not bad else f"RESULT: RED ({bad} failed)")
sys.exit(1 if bad else 0)
