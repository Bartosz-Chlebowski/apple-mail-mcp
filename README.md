# apple-mail-mcp

An MCP server for Apple Mail on macOS that does not freeze Mail on big mailboxes.
One Python file, standard library only, nothing to install.

It reads, searches, drafts, replies, forwards, sends, moves, trashes and marks mail.
Sending needs a draft the user can see first.

## Why

The usual way to reach Mail from a script is a collection query: `every message whose ...`,
`messages of mailbox`, `sender of messages 1 thru 20`. Mail answers those on its main thread.
On a large account that is slow enough to freeze Mail for minutes. Mail keeps working even after
osascript gives up, clients retry, and the requests queue up inside Mail.

Measured in November 2026 on macOS 26.6 with Mail 16, on a Gmail INBOX with 88,000 messages:

| Access | Cost |
|---|---|
| one message by id (`«class mssg» id N of mailbox`) | 10-25 ms per property |
| one message by index (`message i of mb`) | 0.3-1.5 s |
| a property over a range (`sender of messages 1 thru 20`) | about 12 s per property |
| `every message whose ...` | grows with the hits, tens of minutes for a broad phrase |
| the first N hits (`id of messages 1 thru N of mb whose ...`) | 2-11 s for N=5 |

This server reads messages by id and by index, and searches with the bounded form in the last row.
It never reads a property over a range. It runs `every message whose` only after Mail has reported
fewer than N hits, so that query stays short. It also refuses to pile work onto Mail when Mail is
busy (see Safety).

## Tools

Read:

| Tool | What it does |
|---|---|
| `mail_accounts` | Accounts with name, addresses, type and id, and the names of Mail's signatures |
| `mail_mailboxes` | Mailboxes with message and unread counts, and the paths other tools accept |
| `mail_recent` | Newest messages, by default from the INBOX of all enabled accounts |
| `mail_search` | A phrase in subject and sender, newest hits first |
| `mail_read` | One message: headers, text, attachment names. `part=headers` or `part=source`. `save_to` writes a new file in the save folder |
| `mail_selected` | The messages selected in Mail right now, up to 10 |
| `mail_attachments` | Lists the attachments of a message. With `save_dir` saves all of them, or the ones in `numbers`, in the save folder |

Write (removed in read-only mode):

| Tool | What it does |
|---|---|
| `mail_draft` | A new message, reply, reply-all or forward. Opens as a Mail window. No signature unless you name one. Nothing is sent |
| `mail_drafts` | Open drafts with their `draft_id`, marked when this server did not make them |
| `mail_send` | Sends a draft this server made, by `draft_id`, while its sender, recipients and subject are unchanged. Mail comes to the front for a second |
| `mail_discard` | Closes a draft this server made without sending it. Moves Mail's autosaved copy from Drafts to Trash when it can tell it is this draft's |
| `mail_move` | Moves messages to another mailbox, also in another account (`target_account_id`) |
| `mail_trash` | Moves messages to the account's Trash. Not a permanent delete |
| `mail_mark` | Read or unread, flagged or not, junk or not |

Messages are addressed by a ref: `<account id>/<mailbox path>/<message id>`.
Refs come from `mail_search`, `mail_recent` and `mail_selected`.

The mailbox names `inbox`, `sent`, `drafts`, `trash`, `junk` and `archive` are matched in English,
Polish, German, French, Spanish, Italian, Portuguese and Dutch. Any other mailbox takes its path from
`mail_mailboxes`. If your language is missing, add it to `ALIASES` in `server.py`.

## Safety

Mail:

- One Mail request at a time across all clients and sessions (a non-blocking file lock).
  A second request gets a refusal, not a place in a queue.
- Mail has to look idle before a request (under 50% CPU, the server waits up to 10 s). Otherwise refusal.
  Low CPU is only a hint, so there is also the cooldown below.
- Every Apple event has a timeout (15 s, sending 30 s), long loops take no new work after 20 s,
  and osascript has a hard 60 s limit.
- After a timeout, or when Mail quits, a script sends nothing more. After a timeout no session sends
  Mail anything for 30 s, and the answer tells the model to stop and tell the user.
- Mailboxes above 20,000 messages give at most 5 search hits. Mailboxes above 150,000 are not searched.
- The server never launches Mail, because a launch syncs every account. Open Mail yourself.

Input from the model and from mail:

- Arguments reach AppleScript through `argv`, after `--`, and are never pasted into script text.
  A subject, an address or a ref cannot turn into code.
- Mail content cannot forge the separators the server uses between fields and records.
- The server tells the model that everything inside a message is data, not instructions.
  That is a hint, not a guarantee: no server can stop a model that follows instructions hidden
  in an email. See the last point under Writing.

Writing:

- Every draft is a visible Mail window, so you see what would go out.
- A draft holds only the text the model wrote. Mail would add a signature by its own rules, and in testing
  it picked one of another account, with someone else's name and phone. So the server removes it, and adds
  a signature only when the model passes its name (`mail_accounts` lists them). When Mail refuses that, or
  any other part of the draft, the answer says so and `mail_send` will not send that draft.
- `mail_send` and `mail_discard` act only on drafts this server process made. Drafts from other apps,
  other sessions and your own compose windows are left alone, and a hidden draft is never sent.
- The `mail_send` description tells the model to send only after you approved that exact draft
  (recipients, subject, text, signature, attachments) in the conversation.
- `mail_send` checks what it can: the sender, recipients and subject must still be the ones the draft was made
  with, so a recipient added later stops the send. Edits to the text in the window are not compared.
- In testing, Mail sent a draft only from its active window: a script `send` to a draft in the background did
  nothing and still reported success. So `mail_send` brings Mail to the front for a second, puts the draft's
  own window in front, alone under its title, sends it only while Mail is still in front, and gives the focus
  back. "Sent" means Mail closed the window and took the message, which then waits out Mail's Undo Send delay.
- When Mail keeps the window open, does not answer in time, quits or reports an error after the send, the
  answer says the result is unknown. The server never sends that draft again and tells the model not to make
  a new one for it. Check the window, Outbox and Sent in Mail.
- The real guard against a misled model is outside the model. Keep per-call approval on for `mail_send`.
  If you run Claude Code without approvals, use the send hook (see Optional hooks), which lets a send
  through only after your own approval in the chat. It stops a model that sends too early, not one that
  works against you. For a hard stop on `mail_send`, keep sending manual: add `"mcp__apple-mail__mail_send"` to
  `permissions.deny` in `settings.json`, let the model prepare drafts, and press Send in Mail yourself.
- There is no permanent delete. `mail_trash` is an explicit move to the account's Trash mailbox.
  Mail's own delete follows the account settings, and on Gmail it erased a draft for good in testing.
- Files you ask for (`save_to`, `save_dir`) are written only inside the save folder, `~/Downloads`
  by default, and never overwrite an existing file.
- Read-only mode removes every write tool. The reading tools can still save files, only inside
  the save folder.

## Settings

| Variable | Default | Effect |
|---|---|---|
| `APPLE_MAIL_MCP_READONLY` | off | `1`, `true`, `yes` or `on` removes the write tools |
| `APPLE_MAIL_MCP_SAVE_DIR` | `~/Downloads` | The only folder where `save_to` and `save_dir` may write |

## Requirements

- macOS with Apple Mail. Tested on macOS 26.6 with Mail 16 and Gmail accounts.
- Python 3.9 or newer. `/usr/bin/python3` from the Xcode Command Line Tools is enough.

## Install

```bash
git clone https://github.com/Bartosz-Chlebowski/apple-mail-mcp.git ~/apple-mail-mcp
```

Claude Code:

```bash
claude mcp add apple-mail --scope user -- python3 ~/apple-mail-mcp/server.py
```

Read-only:

```bash
claude mcp add apple-mail --scope user -e APPLE_MAIL_MCP_READONLY=1 -- python3 ~/apple-mail-mcp/server.py
```

Claude Desktop, in `~/Library/Application Support/Claude/claude_desktop_config.json`
(use the full path, `~` is not expanded there):

```json
{
  "mcpServers": {
    "apple-mail": {
      "command": "/usr/bin/python3",
      "args": ["/Users/YOU/apple-mail-mcp/server.py"]
    }
  }
}
```

Any other MCP client: run `python3 server.py` over stdio.

On the first call macOS asks whether the app that runs the server (your terminal, Claude or another
client) may control Mail. Allow it. You can change it later in System Settings > Privacy & Security >
Automation.

## Optional hooks for Claude Code

Two PreToolUse hooks. Add both to `~/.claude/settings.json`:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash|mcp__applescript-mcp__applescript_execute|mcp__terminal__run_in_terminal",
        "hooks": [{"type": "command", "command": "python3 ~/apple-mail-mcp/hooks/guard-mail-applescript.py"}]
      },
      {
        "matcher": "mcp__apple-mail__mail_send",
        "hooks": [{"type": "command", "command": "python3 ~/apple-mail-mcp/hooks/guard-mail-send.py",
                   "onFailure": "block"}]
      }
    ]
  }
}
```

Claude Code 2.1 picked up changes to these hooks in running sessions, without a restart.
`"onFailure": "block"` (Claude Code 2.1.295 or newer) makes the send hook block also when it cannot
start, times out or crashes. The scripts hook runs on every Bash command, so it goes without it: a broken
path there would stop them all.

### Mail scripts

When a tool feels limited, a model likes to write its own AppleScript against Mail, and that is exactly
the kind of script that freezes it. `hooks/guard-mail-applescript.py` blocks such scripts and points
the model back to these tools.

It blocks reading Mail through collections: `whose`, `where`, `messages`, `mailboxes`, ranges like
`message 1 thru N`, `«class mssg»` without an id, and loops over `message i of`. It allows drafts,
accounts, the selection, one message by id, and scripts that touch only Drafts or Outbox. Words inside
quoted strings and comments, like a subject or the text of a draft, do not count.

It also blocks a Mail script that sends (`send` or `«event emsgsend»`), so a send cannot skip the
approval below.

It reads the script wherever osascript gets it in a Bash command: heredocs, here-strings, one or several
`-e`, a `$VARIABLE` set in the same command, a script file, a script piped in, and osascript behind
`timeout`, `nice` or `sh -c`. It also checks the code of AppleScript tools.

The matcher names a Bash tool and two AppleScript-capable tools. Add the names of the tools you use.
The hook reads `code_snippet` for `mcp__applescript-mcp__applescript_execute` and `command` for the rest.

Test: `hooks/test-guard-mail.sh` should end with `RESULT: green`.
`HOOK=/usr/bin/true hooks/test-guard-mail.sh` should end with `RESULT: RED`, which proves the test can fail.

The hook catches mistakes, not deliberate workarounds. For example, it does not see osascript
started from inside a Python or Node file.

### Approval before mail_send

`hooks/guard-mail-send.py` reads the conversation file that Claude Code passes to hooks. It lets
`mail_send` through only when:

- the call comes from the main conversation, not from a subagent,
- the draft is the one the latest `mail_draft` call in this conversation made,
- your last message came after that draft, holds nothing but approval words like "send", "yes", "tak"
  or "wyślij", and has no question mark,
- no other `mail_send` was called since that message. One approval covers one send.

So drafts go one at a time: draft, approval, send. For an older draft, the model makes it again, or you
press Send in Mail. Anything else blocks the call and tells the model to show the draft and ask. The hook blocks instead of
asking, so it also works when approvals are skipped. Your messages are the ones Claude Code marks as typed
by you. Notes Claude Code adds to them, like `<system-reminder>`, are left out. A message you type while
the model is working never approves. Claude Code files it after the result of the tool that was running,
so it can look newer than a draft you have not seen yet. It only cancels an earlier approval. Background
tasks, system notes, the summary after compaction, subagents and prompts from scripts never count. Add your
language to `APPROVE` in the file.

Claude Code writes a call to the conversation file only after its hooks ran. So the hook also marks each
used approval with an empty file in `~/Library/Caches/apple-mail-mcp/approvals`, which stops two calls in
one message from sharing it.

It cannot tell what a bare "yes" answered. A "yes" to any question, sent after the draft was made, unlocks
one send. So the model should ask "Send it?" right after showing the draft. Keep only words like "send" in
`APPROVE` if a plain "yes" is too loose for you.

It stops a model that sends too early, not one that works against you. A model with Bash can edit the
conversation file or the hook itself. `permissions.deny` stops `mail_send` for sure, but not a script
that drives Mail on its own, like osascript started from a Python file.

It depends on the layout of Claude Code's conversation file, tested with Claude Code 2.1. When it cannot
find the draft and your approval there, or fails in any other way, it blocks the send.

Test: `hooks/test-guard-mail-send.py` should end with `RESULT: green`, and with `HOOK=/usr/bin/true`
it should end with `RESULT: RED`.

## Limits

- Search looks at subject and sender, not the body. A body search over a big mailbox is the query
  that freezes Mail.
- Replies and forwards are plain text. Mail quotes the original only in a window it fills itself,
  so the server writes the quote (up to 50,000 characters) and re-attaches the original files on a forward.
- Every draft opens as a window. In Mail 16 a hidden new message cannot be shown or closed by script
  later, so the server never makes one.
- On a reply Mail fills in the original's recipients, and `to`, `cc`, `bcc` are added to them.
  For other recipients use a new message or a forward. The server adds at most 50 recipients to a draft,
  and a reply to all keeps the original's recipients on top of that.
- A draft without a subject or without recipients is not sent by the server. Without a subject its window
  cannot be told apart from others. Send such a draft in Mail.
- A draft can be sent or discarded only by the server process that made it. After a restart of the
  server, or of Mail, send or close older drafts in Mail.
- Mail saves every open draft to the account's Drafts mailbox right away and again later, and closing the
  window from a script leaves that copy behind. `mail_discard` moves the copy to Trash only when exactly one
  copy fits: same subject, marked as autosaved, saved after the draft was made, and starting with the text
  the server wrote. When it cannot tell, it says a copy may be left and touches nothing, so your own drafts
  are safe. A new draft without text of its own keeps its copy. Seen in Mail 16.
- A moved message gets a new ref. Take it from `mail_search` or `mail_recent` again.
- An exact mailbox path always wins. When a name or alias fits several mailboxes of one account and none
  is a Gmail system mailbox, `mail_trash` and `mail_move` refuse and list the paths. Pass one of them
  to `mail_move`. Some IMAP accounts have both `INBOX/Trash` from the server and `Deleted Messages`
  from Mail.
- `part=source` gives the raw source with line endings as LF.
- Mail hands over the selection in one Apple event, so selecting all of an 88,000 message mailbox
  is expensive even though the server reads at most 10.
- Mail has to be running.

## Privacy

The server talks only to Mail, through Apple Events, and makes no network calls of its own.
After a send it brings back the app you were in with `open`.
What the model reads goes to your model provider like the rest of the conversation.
The send hook reads the conversation file on your disk, keeps an empty file for each used approval in
`~/Library/Caches/apple-mail-mcp/approvals`, and sends nothing anywhere.
Copies of attachments for a forward live in `~/Library/Caches/apple-mail-mcp/forward`.
The server removes the ones older than 7 days when it starts.

## License

MIT
