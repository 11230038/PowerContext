"""End-to-end validation for the Cat Tavern Dify chatflow.

The script talks to a running deployment through Dify's public service API
(``POST /v1/chat-messages``) and through the tavern backend's evidence
endpoints, then checks that:

1. a brand-new player gets an in-character answer and the deed is stored;
2. the same player, in a *new conversation*, is answered from memory;
3. a different player is not shown any of the first player's deeds;
4. every answer was grounded in seekdb lore hits.

Usage::

    python samples/validate_cat_tavern.py \
        --dify-base http://localhost:8080 \
        --api-key app-xxxxxxxx \
        --tavern-base http://127.0.0.1:8090 \
        --out artifacts

Exit code is 0 only when every check passes.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

FOOTER = re.compile(
    r"好感度\s*(?P<affinity>-?\d+)（(?P<label>[^）]+)）"
    r"｜旧事\s*(?P<deeds>\d+)\s*条"
    r"｜传闻\s*(?P<lore>[^\n]+)"
)


def post_json(url: str, payload: dict, headers: dict[str, str] | None = None) -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.loads(response.read().decode("utf-8"))


def get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def ask(
    dify_base: str,
    api_key: str,
    *,
    player_id: str,
    session_id: str,
    query: str,
    user: str,
) -> dict:
    """Send one chat message and collect the streamed answer + events."""
    body = json.dumps(
        {
            "inputs": {"player_id": player_id, "session_id": session_id},
            "query": query,
            "response_mode": "streaming",
            "user": user,
            "conversation_id": None,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{dify_base}/v1/chat-messages",
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )

    chunks: list[str] = []
    conversation_id = ""
    error = ""
    with urllib.request.urlopen(request, timeout=180) as response:
        for raw in response:
            line = raw.decode("utf-8").strip()
            if not line.startswith("data:"):
                continue
            try:
                event = json.loads(line[5:].strip())
            except json.JSONDecodeError:
                continue
            kind = event.get("event")
            if kind in {"message", "agent_message"}:
                chunks.append(event.get("answer", ""))
            elif kind == "message_end":
                conversation_id = event.get("conversation_id", conversation_id)
            elif kind == "error":
                error = event.get("message", "unknown error")

    answer = "".join(chunks).strip()
    footer = FOOTER.search(answer)
    body = answer.split("\n---\n", 1)[0].strip()
    return {
        "player_id": player_id,
        "session_id": session_id,
        "query": query,
        "conversation_id": conversation_id,
        "answer": answer,
        "body": body,
        "error": error,
        "affinity": int(footer.group("affinity")) if footer else None,
        "affinity_label": footer.group("label") if footer else None,
        "deed_count": int(footer.group("deeds")) if footer else None,
        "lore_ids": footer.group("lore").strip() if footer else "",
    }


def reset(tavern_base: str, player_id: str) -> None:
    request = urllib.request.Request(
        f"{tavern_base}/debug/reset/{urllib.parse.quote(player_id)}", method="POST"
    )
    with urllib.request.urlopen(request, timeout=30):
        pass


def state(tavern_base: str, player_id: str) -> dict:
    return get_json(f"{tavern_base}/debug/state/{urllib.parse.quote(player_id)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dify-base", default="http://localhost:8080")
    parser.add_argument("--api-key", required=True)
    parser.add_argument("--tavern-base", default="http://127.0.0.1:8090")
    parser.add_argument("--out", default="artifacts")
    parser.add_argument("--player-a", default="validator_a")
    parser.add_argument("--player-b", default="validator_b")
    args = parser.parse_args()

    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    for player in (args.player_a, args.player_b):
        reset(args.tavern_base, player)

    checks: list[dict] = []

    def check(name: str, ok: bool, detail: str) -> None:
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    try:
        health = get_json(f"{args.tavern_base}/health")
    except urllib.error.URLError as error:
        print(f"backend not reachable: {error}", file=sys.stderr)
        return 2

    first = ask(
        args.dify_base,
        args.api_key,
        player_id=args.player_a,
        session_id="a1",
        query="老白，是我把你柜台上的鱼干全偷吃了，你怎么一点反应都没有？",
        user="validator",
    )
    check(
        "session a answered in character",
        len(first["body"]) >= 10 and not first["error"],
        first["error"] or f"{len(first['body'])} chars before the status footer",
    )
    check(
        "session a starts without memory",
        first["deed_count"] == 0,
        f"deed_count={first['deed_count']}",
    )
    check(
        "session a grounded in seekdb lore",
        bool(first["lore_ids"]) and first["lore_ids"] != "-",
        f"lore={first['lore_ids']}",
    )

    after_first = state(args.tavern_base, args.player_a)
    deeds = after_first["memory"]["deeds"]
    check(
        "deed stored in PowerContext",
        len(deeds) == 1 and "鱼干" in deeds[0]["text"],
        f"deeds={[item['text'] for item in deeds]}",
    )

    second = ask(
        args.dify_base,
        args.api_key,
        player_id=args.player_a,
        session_id="a2",
        query="我今天又来了，你还记得我上回干了什么吗？",
        user="validator",
    )
    check(
        "session b (new conversation) recalls the deed",
        second["deed_count"] == 1,
        f"deed_count={second['deed_count']}, affinity={second['affinity']}",
    )
    check(
        "memory changed the tone",
        second["affinity"] is not None and second["affinity"] < first["affinity"],
        f"{first['affinity']} -> {second['affinity']}",
    )

    other = ask(
        args.dify_base,
        args.api_key,
        player_id=args.player_b,
        session_id="b1",
        query="我今天又来了，你还记得我上回干了什么吗？",
        user="validator",
    )
    check(
        "second player isolated from first player's memory",
        other["deed_count"] == 0,
        f"deed_count={other['deed_count']}",
    )

    after_other = state(args.tavern_base, args.player_b)
    check(
        "isolation confirmed in PowerContext",
        len(after_other["memory"]["deeds"]) == 1
        and after_other["memory"]["deeds"][0]["text"] != deeds[0]["text"],
        f"player_b deeds={[item['text'] for item in after_other['memory']['deeds']]}",
    )

    queries = after_first["recent_lore_queries"]
    check(
        "seekdb query log recorded",
        bool(queries) and all(item["hits"] for item in queries),
        f"{len(queries)} queries",
    )

    report = {
        "generated_at": stamp,
        "dify_base": args.dify_base,
        "tavern_base": args.tavern_base,
        "health": health,
        "runs": [first, second, other],
        "state_player_a": after_first,
        "state_player_b": after_other,
        "checks": checks,
        "passed": sum(1 for item in checks if item["ok"]),
        "total": len(checks),
    }

    target = out / f"validation-{stamp}.json"
    target.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    lines = [
        f"# Cat Tavern validation {stamp}",
        "",
        f"- backend: {args.tavern_base} ({health['engine_version']}, "
        f"{health['lore_cards']} lore cards)",
        f"- dify: {args.dify_base}",
        f"- result: **{report['passed']}/{report['total']} checks passed**",
        "",
        "## Runs",
        "",
    ]
    for run in report["runs"]:
        lines += [
            f"### {run['player_id']} / {run['session_id']}",
            "",
            f"> {run['query']}",
            "",
            run["answer"] or "*(empty)*",
            "",
            f"- conversation: `{run['conversation_id']}`",
            f"- deeds seen: {run['deed_count']} · affinity: {run['affinity']} "
            f"({run['affinity_label']}) · lore: {run['lore_ids']}",
            "",
        ]
    lines += ["## Checks", ""]
    for item in checks:
        mark = "PASS" if item["ok"] else "FAIL"
        lines.append(f"- [{mark}] {item['check']} — {item['detail']}")
    lines.append("")

    (out / f"validation-{stamp}.md").write_text("\n".join(lines), encoding="utf-8")

    for item in checks:
        print(("PASS " if item["ok"] else "FAIL ") + item["check"] + " — " + item["detail"])
    print(f"{report['passed']}/{report['total']} checks passed; wrote {target}")
    return 0 if report["passed"] == report["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
