#!/usr/bin/env python3
import api
import datetime
import logging

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
        api.backup(instance['uid'], trigger=trigger)
        _logger.info(f"Backup done {instance['uid']}")

def delete_old_backups():
    pass

if __name__ == "__main__":
    create_scheduled_backups()
    delete_old_backups()

