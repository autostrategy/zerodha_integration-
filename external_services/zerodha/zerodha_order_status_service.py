from config import default_log
from typing import Optional


class ZerodhaOrderStatusService:
    order_status_dictionary = {}
    order_id_queue = []

    def __init__(self, zerodha_order_id: int = None):
        if zerodha_order_id is None:
            zerodha_orders = get_all_pending_zerodha_orders()

            zerodha_order_ids = [z.order_id for z in zerodha_orders]

            self.order_id_queue.extend(zerodha_order_ids)
        else:
            self.order_id_queue.append(zerodha_order_id)
