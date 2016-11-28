# -*- coding: utf-8 -*-
from time import time, mktime
from datetime import datetime
from iso8601 import parse_date
from socket import setdefaulttimeout
from retrying import retry

from openprocurement_client.client import TendersClient
from openprocurement.search.source import BaseSource

from logging import getLogger
logger = getLogger(__name__)


class PlanSource(BaseSource):
    """Plan Source from open openprocurement.API.plans
    """
    __doc_type__ = 'plan'

    config = {
        'plan_api_key': '',
        'plan_api_url': "",
        'plan_api_version': '0',
        'plan_resource': 'plans',
        'plan_api_mode': '',
        'plan_skip_until': None,
        'plan_limit': 1000,
        'plan_preload': 500000,
        'plan_resethours': [23],
        'timeout': 30,
    }

    def __init__(self, config={}):
        if config:
            self.config.update(config)
        self.config['plan_limit'] = int(self.config['plan_limit'] or 0) or 100
        self.config['plan_preload'] = int(self.config['plan_preload'] or 0) or 100
        self.client = None

    def procuring_entity(self, item):
        return item.data.get('procuringEntity', None)

    def patch_version(self, item):
        """Convert dateModified to long version
        """
        item['doc_type'] = self.__doc_type__
        dt = parse_date(item['dateModified'])
        version = 1e6 * mktime(dt.timetuple()) + dt.microsecond
        item['version'] = long(version)
        return item

    def need_reset(self):
        if time() - self.last_reset_time > 4000:
            return datetime.now().hour in self.config['plan_resethours']

    @retry(stop_max_attempt_number=5, wait_fixed=15000)
    def reset(self):
        logger.info("Reset plans, plan_skip_until=%s",
                    self.config['plan_skip_until'])
        if self.config.get('timeout', None):
            setdefaulttimeout(float(self.config['timeout']))
        params = {}
        if self.config['plan_api_mode']:
            params['mode'] = self.config['plan_api_mode']
        if self.config['plan_limit']:
            params['limit'] = self.config['plan_limit']
        self.client = TendersClient(
            key=self.config['plan_api_key'],
            host_url=self.config['plan_api_url'],
            api_version=self.config['plan_api_version'],
            resource=self.config['plan_resource'],
            params=params)
        self.skip_until = self.config.get('plan_skip_until', None)
        if self.skip_until and self.skip_until[:2] != '20':
            self.skip_until = None
        self.last_reset_time = time()

    def preload(self):
        preload_items = []
        while True:
            try:
                items = self.client.get_tenders()
            except Exception as e:
                logger.error("PlanSource.preload error %s", str(e))
                self.reset()
                break
            if self.should_exit:
                return []
            if not items:
                break

            preload_items.extend(items)

            if len(preload_items) >= 100:
                logger.info("Preload %d plans, last %s",
                    len(preload_items), items[-1]['dateModified'])
            if len(items) < 10:
                break
            if len(preload_items) >= self.config['plan_preload']:
                break

        return preload_items

    def items(self):
        if not self.client:
            self.reset()
        self.last_skipped = None
        for plan in self.preload():
            if self.should_exit:
                raise StopIteration()
            if self.skip_until > plan['dateModified']:
                self.last_skipped = plan['dateModified']
                continue
            yield self.patch_version(plan)

    def get(self, item):
        plan = {}
        retry_count = 0
        while not self.should_exit:
            try:
                plan = self.client.get_tender(item['id'])
                assert plan['data']['id'] == item['id']
                assert plan['data']['dateModified'] >= item['dateModified']
                break
            except Exception as e:
                if retry_count > 3:
                    raise e
                retry_count += 1
                logger.error("get_plan %s retry %d error %s",
                    str(item['id']), retry_count, str(e))
                self.sleep(5)
                if retry_count > 1:
                    self.reset()
        if item['dateModified'] != plan['data']['dateModified']:
            logger.debug("Plan dateModified mismatch %s %s %s",
                item['id'], item['dateModified'],
                plan['data']['dateModified'])
            item['dateModified'] = plan['data']['dateModified']
            item = self.patch_version(item)
        plan['meta'] = item
        return plan
