# -*- coding: utf-8 -*-
from datetime import datetime
import simplejson as json

from openprocurement.search.index import BaseIndex, logger

class TenderIndex(BaseIndex):
    """OpenProcurement Tenders Index
    """
    __index_name__ = 'tenders'

    def before_index_item(self, item):
        entity = self.source.procuring_entity(item)
        if entity:
            self.engine.index_by_type('org', entity)

    def test_noindex(self, item):
        # noindex filter by procurementMethodType should working
        # only for tenders created since 2016-05-31
        if item.data.tenderID > 'UA-2016-05-31':
            proc_type = item.data.procurementMethodType
            if proc_type == 'negotiation' or proc_type == 'negotiation.quick':
                active = 0
                for award in item.data.get('awards', []):
                    if award.get('status', '') == 'active':
                        active += 1
                        break
                if active == 0:
                    return True
            elif proc_type == 'reporting':
                active = 0
                for contract in item.data.get('contracts', []):
                    if contract.get('status', '') == 'active':
                        active += 1
                        break
                if active == 0:
                    return True

        return False

    def need_reindex(self):
        if not self.current_index:
            return True
        if self.index_age() > 120*3600:
            return datetime.now().isoweekday() >= 6
        return False

    def create_index(self, name):
        tender_index = self.config['tender_index']
        logger.info("[%s] Create new tender index from %s",
            name, tender_index)
        with open(tender_index) as f:
            body = json.load(f)
        self.engine.create_index(name, body=body)
