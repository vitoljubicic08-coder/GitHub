"""Command line: python -m quotebook <command> [options]. Run from aibiz/mvp/.

  check-config          validate the business JSON
  init                  create or upgrade the database (backs up an existing one first)
  seed                  add simulated customers and bookings (fictional data only)
  serve                 run the demo website, chat API and admin page
  jobs [--loop SEC]     expire holds, queue follow-ups, deliver the outbox (dry run)
  backup / restore F    copy the database to/from a file
  purge                 apply the data-retention rules
  export-customer PHONE print everything stored about one customer (GDPR access request)
  transcripts           replay the example conversations into docs/EXAMPLE_CONVERSATIONS.md
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

from . import logs
from .assistant import App
from .config import ConfigError, Env, load_config, validate
from .db import Database

log = logging.getLogger("quotebook")


def build_app(args) -> App:
    cfg = load_config(args.config)
    env = Env.from_environ()
    interp = None
    if env.anthropic_enabled:
        from .llm import LLMInterpreter
        interp = LLMInterpreter.from_env(cfg)
        log.info("AI interpreter enabled (model %s)", cfg.assistant["llm_model"])
    return App(cfg, Database(args.db), env, var_dir=args.var, interpreter=interp)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="quotebook", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="config/demo_detailing.json")
    ap.add_argument("--db", default="var/quotebook.sqlite3")
    ap.add_argument("--var", default="var")
    ap.add_argument("--log-level", default="INFO")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check-config")
    sub.add_parser("init")
    sub.add_parser("seed")
    s = sub.add_parser("serve")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)
    s.add_argument("--trust-proxy", action="store_true", help="use X-Forwarded-For (only behind your own proxy)")
    s.add_argument("--secure-cookies", action="store_true", help="mark the admin cookie Secure (HTTPS deployments)")
    j = sub.add_parser("jobs")
    j.add_argument("--loop", type=float, default=0, help="repeat every N seconds")
    b = sub.add_parser("backup")
    b.add_argument("dest", nargs="?")
    r = sub.add_parser("restore")
    r.add_argument("src")
    sub.add_parser("purge")
    x = sub.add_parser("export-customer")
    x.add_argument("phone")
    sub.add_parser("transcripts")
    args = ap.parse_args(argv)
    Path(args.var).mkdir(parents=True, exist_ok=True)
    logs.setup(args.log_level, str(Path(args.var) / "quotebook.log"))

    if args.cmd == "check-config":
        raw = json.loads(Path(args.config).read_text(encoding="utf-8"))
        errs = validate(raw)
        print("OK" if not errs else "\n".join("ERROR: " + e for e in errs))
        return 1 if errs else 0
    try:
        app = build_app(args)
    except ConfigError as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        return 2
    db = app.db
    if args.cmd == "restore":
        db.restore(args.src)
        print(f"restored {args.src} -> {args.db}")
        return 0
    if args.cmd == "init":
        v = db.migrate(backup_dir=Path(args.var) / "backups")
        print(f"database ready at {args.db} (schema v{v})")
        return 0
    db.migrate(backup_dir=Path(args.var) / "backups")
    if args.cmd == "seed":
        from .seed import seed
        print(json.dumps(seed(app), indent=1))
    elif args.cmd == "serve":
        from .web import serve
        srv = serve(app, args.host, args.port, args.trust_proxy, args.secure_cookies)
        print(f"Demo running at http://{args.host}:{args.port}/  (admin: /admin)  Ctrl+C to stop")
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            srv.server_close()
    elif args.cmd == "jobs":
        while True:
            try:
                print(json.dumps(app.run_jobs()))
            except Exception:
                log.exception("job run failed; will retry")
            if not args.loop:
                break
            time.sleep(args.loop)
    elif args.cmd == "backup":
        dest = args.dest or str(Path(args.var) / "backups" / f"quotebook-{time.strftime('%Y%m%d-%H%M%S')}.sqlite3")
        print(db.backup(dest))
    elif args.cmd == "purge":
        print(json.dumps(app.purge()))
    elif args.cmd == "export-customer":
        print(json.dumps(app.export_customer(args.phone), indent=1, ensure_ascii=False, default=str))
    elif args.cmd == "transcripts":
        from .transcripts import write_transcripts
        print(write_transcripts(Path("docs/EXAMPLE_CONVERSATIONS.md")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
