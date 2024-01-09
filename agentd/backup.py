#!/usr/bin/env python3
import api

if __name__ == "__main__":
    curstatus = api.status()
    for instance in curstatus['instances']:
        api.backup(instance['uid'])

