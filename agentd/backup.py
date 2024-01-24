#!/usr/bin/env python3
import api
import agentlib
import datetime
import logging
import glob

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s %(levelname)s %(name)s: %(message)s'
)

_logger = logging.getLogger(__name__)

def create_scheduled_backups():
    today = datetime.date.today()
    if today.day == 1:
        trigger = 'monthly'
    elif today.isoweekday() == 1:
        trigger = 'weekly'
    else:
        trigger = 'daily'

    insts = api.status()['instances']
    _logger.info(f"Creating scheduled backups for {len(insts)} instances.")
    for instance in insts:
        resp = api.backup(instance['uid'], trigger=trigger)
        _logger.info(resp['fshealth'])
        backups_paths = glob.glob(agentlib.dump_path(uid, trigger, '*.pgc'))
        backups_paths.sort(reverse=True)
        for remove in backups_paths[:3]:
            _logger.info("Remove %s", remove)
            # TODO:

if __name__ == "__main__":
    create_scheduled_backups()

