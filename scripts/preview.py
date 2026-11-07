"""Serve the real app on its own port, for inspecting the UI.

A verification harness, not a deployment target. It runs the same routes against
the same platforms as `just ui` — the point is to look at what the app actually
renders, so substituting fixtures would only confirm whatever the fixtures were
written to show. Real data is where the awkward cases live: league names with
emoji in them, a preseason week where every projection is zero, a squad of
fifteen rather than a tidy three.

It differs from `just ui` only in the port, so a running `just ui` keeps its
own. Whether analysis appears depends on GOOGLE_API_KEY, exactly as it does in
the real thing — which is itself worth being able to look at both ways.

Run with `just preview`.
"""

PORT = 8100


def main() -> int:
    import uvicorn

    from thefrontoffice.adapters.inbound.web.api import serve

    print(f"\n  Preview on http://127.0.0.1:{PORT}\n")
    uvicorn.run(serve(), host="127.0.0.1", port=PORT, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
