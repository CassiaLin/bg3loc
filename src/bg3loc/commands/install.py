from __future__ import annotations

import argparse
from pathlib import Path

from bg3loc.installer import InstallFailure, InstallRequest, run_install


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p = subparsers.add_parser("install", help="Safely deploy rebuilt localization artifacts")
    p.add_argument("--rebuild", default="workspace/rebuild/rebuild-manifest.json")
    p.add_argument("--scan", default="workspace/scan-manifest.json")
    p.add_argument("--game-dir")
    p.add_argument("--backup-dir", default="workspace/backups")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--rollback")
    p.set_defaults(handler=run)


def run(args: argparse.Namespace) -> int:
    request = InstallRequest(
        rebuild_manifest=Path(args.rebuild),
        scan_manifest=Path(args.scan),
        game_dir=Path(args.game_dir) if args.game_dir else None,
        backup_dir=Path(args.backup_dir),
        dry_run=bool(args.dry_run),
        rollback_manifest=Path(args.rollback) if args.rollback else None,
    )
    try:
        result = run_install(request)
    except InstallFailure as exc:
        from bg3loc.errors import BG3LocError
        raise BG3LocError(exc.exit_code, exc.key, exc.message) from exc
    if args.dry_run:
        print("Install dry-run PASS")
        print(f"Target: {result['preflight']['destination']}")
        print("Backup: would be created on real install | Game modified: no")
    elif args.rollback:
        print("Rollback PASS")
        print(f"Restored: {result['destination']} | SHA256: {result['restoredSha256']}")
    else:
        deployment = result["deployment"][0]
        print("Install PASS")
        print(f"Installed: {deployment['destination']}")
        print(f"Backup: {deployment['backupPath']} | Rollback available: yes")
    return 0
