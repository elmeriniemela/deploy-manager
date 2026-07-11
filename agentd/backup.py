#!/usr/bin/env python3
import argparse
import api
import agentlib
import datetime
import logging
import glob
import os

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s %(levelname)s %(name)s: %(message)s'
)

_logger = logging.getLogger(__name__)

def create_scheduled_backups(dryrun=False):
    today = datetime.date.today()
    if today.day == 1:
        if (today.month-1) % 3 == 0:
            trigger = 'quarterly'
        else:
            trigger = 'monthly'
    elif today.isoweekday() == 1:
        trigger = 'weekly'
    else:
        trigger = 'daily'

    insts = agentlib.list_instances()
    _logger.info(f"Creating scheduled backups for {len(insts)} instances.")
    for instance in insts:
        uid = instance['uid']
        if not dryrun:
            api.backup(uid, trigger=trigger)
        backups_paths = glob.glob(agentlib.dump_path(uid, trigger, '*.pgc'))
        backups_paths.sort(reverse=True) # reverse=True -> desc -> largest/latest first
        n = 3 # Remove all except n latest dumps.
        for remove in backups_paths[n:]:
            _logger.info("Remove %s", remove)
            if not dryrun:
                os.remove(remove)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--dryrun', '--dry-run', action='store_true')
    args = parser.parse_args()
    create_scheduled_backups(dryrun=args.dryrun)
