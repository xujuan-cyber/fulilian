# FuLiLian CTF Extension API

This document defines the supported extension surface for the CTF workflow.

## Client / Server (F4-010)

Start the headless backend with `fulilian serve`. The backend exposes the
existing authenticated JSON-RPC/WebSocket gateway and OpenAI-compatible HTTP
API. CTF-specific local automation should use the dedicated solve RPC below
when a process-local stdin/stdout transport is sufficient.

The CTF solve RPC is newline-delimited JSON-RPC 2.0:

```json
{"jsonrpc":"2.0","id":1,"method":"health"}
{"jsonrpc":"2.0","id":2,"method":"solve","params":{"id":"web-01","model":""}}
```

Every non-empty input line receives exactly one response line. Supported
methods are `health` and `solve`. Invalid JSON returns error `-32700`; unknown
methods return `-32601`; missing `params.id` returns `-32602`.

Run it with:

```bash
fulilian solve --rpc ignored
```

The process reads requests until stdin closes. Model selection, race,
multi-agent, and Architect options may be supplied in `solve.params`.

## TUI (F4-011)

The current supported terminal UI is the Ink/TypeScript client launched with
`fulilian --tui`. It uses the existing Python gateway over stdio JSON-RPC.
There is no Bubble Tea implementation in this repository. Bubble Tea is a
technology-specific migration item, not a separate user-facing capability;
the existing TUI and gateway remain the supported implementation.

## Extension API (F4-012)

The stable Python extension points are:

- `fulilian_ctf.verify.verify_flag_with_report`
- `fulilian_ctf.blackboard.Blackboard`
- `fulilian_ctf.dispatcher.Dispatcher`
- `fulilian_ctf.multi_agent.run_multi_agent`
- `fulilian_ctf.multi_agent.run_boomerang`
- `fulilian_ctf.solve_rpc.handle_request`
- `fulilian_ctf.solve_rpc.serve`

CTF tools are registered in the `ctf_solve` toolset. Tool and hook failures
must not silently turn an unverified flag into a confirmed flag; verification
is fail-closed at the negation gate.
