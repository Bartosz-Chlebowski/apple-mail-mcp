#!/usr/bin/env python3
# Optional Claude Code PreToolUse hook for Bash, mcp__applescript-mcp__applescript_execute and
# mcp__terminal__run_in_terminal (see README).
# Blocks your own AppleScript or JXA that reads Apple Mail through collections: whose/where, messages,
# mailboxes, a range "message 1 thru N", a loop over "message i of". On a Gmail with 88,000 messages such a
# script freezes Mail for minutes, and Mail keeps working even after osascript has given up.
# Mail goes through the mcp__apple-mail__* tools of this repository instead.
# Lets through: drafts (make new outgoing message), accounts (also "account whose"), the selection, one message
# by id, and scripts that touch only the Drafts or Outbox mailbox (they are small).
# Words inside quoted strings (a subject, the text of a draft) and inside comments do not count.
# Finds scripts in heredocs, -e values (several -e are one script, $VAR from the same command is expanded),
# files run by osascript (also <file, $(cat file), $VAR, cd in the same command, the session folder),
# a script piped into osascript (also cat file |), a here-string (<<<), timeout, nice, export and sh -c in front of
# it, and in the code_snippet, code, script or source of AppleScript tools.
# Gap: osascript started from a Python or Node file is not seen. Test: hooks/test-guard-mail.sh
# Every heredoc with such an AppleScript counts as a script, even when it only writes a file.
# Exit 2 = block (stderr goes to the model). Exit 0 = allow. Unreadable input = allow.
import json, os, re, shlex, sys

APP = r'''(?:Mail(?:\.app)?|com\.apple\.mail|[^"'\n]*/Mail\.app/?)'''
MAIL = re.compile(r'''\bapp(?:lication)?\s+(?:id\s+)?"''' + APP + r'''"|Application\(\s*["']''' + APP + r'''["']\s*\)''', re.I)
COLLECTION = re.compile(r'''\b(?:whose|where)\b|(?<!outgoing )(?<!selected )\bmessages\b|\bevery\s+message\b|\bmailboxes\b|'''
                        r'''\bmessages?\s+\S+\s+thru\b|(?:«|<<)class mssg(?:»|>>)(?!\s+id\b)''', re.I)
LOOP_BY_INDEX = re.compile(r'''\brepeat\b[\s\S]*\bmessage\s+(?!(?:id|signature|size|viewers?|caching|font)\b)(?:\(\s*\w+\s*\)|\w+)\s+of\b''', re.I)
ACCOUNTS = re.compile(r'''\b(?:accounts?|outgoing\s+messages?)\s+(?:whose|where)\b''', re.I)  # only a few accounts and compose windows
MAILBOX = re.compile(r'''\bmailbox\s+("[^"]*"|\S+)|\b(inbox|outbox|drafts\s+mailbox|sent\s+mailbox|junk\s+mailbox|trash\s+mailbox|mailboxes)\b''', re.I)
DRAFTS = re.compile(r'''"(?:\[gmail\]/)?(?:drafts|wersje robocze|robocze|szkice|kopie robocze|entwürfe|brouillons|borradores|bozze|rascunhos|concepten)"|outbox|drafts\s+mailbox''', re.I)
HEREDOC = re.compile(r'''<<-?\s*(['"]?)([A-Za-z_]\w*)\1[^\n]*\n(.*?)\n[ \t]*\2[ \t]*(?=\n|$)''', re.S)
SEPARATORS = {";", "&", "&&", "|", "||", "(", ")", "\n"}
WRAPPERS = {"sudo", "time", "nohup", "nice", "env", "export", "exec", "command", "then", "do", "else", "{"}
SHELLS = {"sh", "bash", "zsh", "dash", "ksh"}
REDIRECTS = {">", ">>", ">&", "<&", "&>", ">|"}

REASON = (
    "STOP: this AppleScript reads Apple Mail through collections (whose / where / messages / mailboxes / a range / "
    "a loop over message N). On a big mailbox it freezes Mail for minutes, and Mail keeps working even after "
    "osascript gives up. Use the mcp__apple-mail__ tools: mail_selected (the message the user has open), "
    "mail_search, mail_recent, mail_read (part=headers/source, save_to for a file), mail_attachments, mail_mailboxes, "
    "mail_accounts; to write: mail_draft (new, reply, forward), mail_send, mail_move, mail_trash, mail_mark. "
    "Allowed here: a draft (make new outgoing message), a script that touches only the Drafts or Outbox mailbox, "
    'and one message by its id from a ref: «class mssg» id N of mailbox "X" of account id "Y".'
)


def code(script, keep_strings=False):
    """The script without comments and, unless keep_strings, without quoted strings, so a subject, the text of a
    draft or a note cannot pose as a command."""
    jxa = "Application(" in script
    tok = r'"(?:\\.|[^"\\])*"' + (r"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`|//[^\n]*|/\*[\s\S]*?\*/" if jxa
                                     else r"|--[^\n]*|#[^\n]*|\(\*[\s\S]*?\*\)")
    return re.sub(tok, lambda m: (m[0] if keep_strings else '""') if m[0][0] in "\"'`" else " ", script)


def drafts_only(script):
    """Every mailbox in the script is Drafts or Outbox. Strings other than mailbox names are blanked."""
    k = re.sub(r'(\bmailbox\s+)?"(?:\\.|[^"\\])*"', lambda m: m[0] if m[1] else '""', code(script, keep_strings=True))
    refs = [m[0] for m in MAILBOX.finditer(k)]
    return bool(refs) and all(DRAFTS.fullmatch(re.sub(r"^mailbox\s+", "", r, flags=re.I)) for r in refs)


def reads_collections(script):
    if not MAIL.search(script):
        return False
    k = ACCOUNTS.sub("account", code(script))
    if not (COLLECTION.search(k) or LOOP_BY_INDEX.search(k)):
        return False
    return not drafts_only(script)


def scripts_in(cmd, cwd, depth=0):
    """Texts the command will hand to osascript: heredocs, -e values, program and input files, a piped script."""
    out = [m[3] for m in HEREDOC.finditer(cmd)]
    rest = HEREDOC.sub("\n", cmd).replace("$(pwd)", "$PWD").replace("`pwd`", "$PWD")
    try:
        lex = shlex.shlex(rest, posix=True, punctuation_chars=";&|<>()\n")
        lex.whitespace, lex.whitespace_split, lex.commenters = " \t\r", True, ""
        t = [";" if x and set(x) <= set(";&|()\n") else x for x in lex]  # "\n\n" or ";\n" is one token
    except ValueError:
        return out + [rest.replace('\\"', '"')]
    variables, base = {}, cwd or os.getcwd()

    def expand(p):
        for _ in range(2):  # a variable can point at a variable: S="$TMPDIR/x"
            p = re.sub(r"\$\{?([A-Za-z_]\w*)\}?",
                       lambda m: base if m[1] == "PWD" else variables.get(m[1], os.environ.get(m[1], m[0])), p)
        return p

    def path(p):
        p = os.path.expanduser(expand(p))
        return os.path.normpath(p if os.path.isabs(p) else os.path.join(base, p))

    def read(p):
        f = path(p)
        try:
            if os.path.isfile(f) and os.path.getsize(f) < 512 * 1024:
                with open(f, encoding="utf-8", errors="ignore") as fh:
                    return fh.read()
        except OSError:
            pass
        return ""

    at_command, i = True, 0  # at_command: the next token is a command name
    while i < len(t):
        x = t[i]
        if x in SEPARATORS:
            at_command = True
        elif at_command and re.fullmatch(r"[A-Za-z_]\w*=.*", x, re.S):
            k, v = x.split("=", 1)
            variables[k] = v
        elif at_command and x in WRAPPERS:
            pass
        elif at_command and x in ("timeout", "gtimeout"):  # timeout [options] DURATION command
            while i + 1 < len(t) and t[i + 1] not in SEPARATORS and not re.fullmatch(r"\d+(?:\.\d+)?[smhd]?", t[i + 1]):
                i += 1
            i += 1
        elif at_command and x == "cd" and i + 1 < len(t) and t[i + 1] not in SEPARATORS:
            base = path(t[i + 1])
            i, at_command = i + 1, False
        elif at_command and os.path.basename(x) in SHELLS and i + 2 < len(t) and re.fullmatch(r"-\w*c\w*", t[i + 1]):
            if depth < 3:
                out += scripts_in(t[i + 2], base, depth + 1)
            i, at_command = i + 2, False
        elif at_command and os.path.basename(x) == "osascript":
            j, es, program = i + 1, [], False
            while j < len(t) and t[j] not in SEPARATORS:
                a = t[j]
                if a in REDIRECTS or (a.isdigit() and j + 1 < len(t) and t[j + 1] in REDIRECTS):
                    j += 1 if a.isdigit() else 2  # 2>&1, > out.txt
                    continue
                if a == "-e" and j + 1 < len(t):
                    es.append(expand(t[j + 1]))
                    out += [read(p) for p in re.findall(r"\$\(\s*cat\s+([^)\s]+)\s*\)", t[j + 1])]
                    j += 2
                    continue
                if a == "<<<" and j + 1 < len(t):  # a here-string is the script itself
                    out.append(expand(t[j + 1]))
                    program = True
                    j += 2
                    continue
                if a in ("-l", "-s", "<") and j + 1 < len(t):
                    if a == "<":
                        out.append(read(t[j + 1]))
                        program = True
                    j += 2
                    continue
                if not a.startswith("-") and not es and not program:
                    out.append(read(a))
                    program = True
                j += 1
            if es:
                out.append("\n".join(es))  # several -e make one script
            elif not program:  # the script comes on stdin: echo '...' | osascript, cat file | osascript
                out += [expand(y) for y in t if MAIL.search(y)]
                out += [read(y) for y in t if y not in SEPARATORS and os.path.isfile(path(y))]
            i, at_command = j - 1, False
        else:
            at_command = False
        i += 1
    return out


def main():
    try:
        d = json.load(sys.stdin)
        inp = d.get("tool_input") or {}
    except Exception:
        return 0
    # Bash and terminals pass a command; AppleScript tools pass the script itself under one of these names
    scripts = scripts_in(inp["command"], d.get("cwd")) if isinstance(inp.get("command"), str) else []
    scripts += [v for k, v in inp.items() if k in ("code_snippet", "code", "script", "source") and isinstance(v, str)]
    if any(reads_collections(s) for s in scripts if s):
        print(REASON, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
